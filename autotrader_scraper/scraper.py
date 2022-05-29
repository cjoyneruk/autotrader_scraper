import pandas as pd
from bs4 import BeautifulSoup
import traceback
import cloudscraper
import os
import re

class Scraper:

	"""min_year=1995, max_year=1995, include_writeoff="include"
	"""

	base_url = "https://www.autotrader.co.uk/results-car-search"

	def __init__(self, make="BMW", model="5 SERIES", postcode="SW1A 0AA", radius=10, **kwargs):		
		self.results = []

		self.search_params = {
			"make": make,
			"model": model,
			"postcode": postcode,
			"radius": radius
		}

		self.search_params.update(kwargs)
		
	@staticmethod
	def _get_regex(pattern, string, type_=str, group_no=1):

		regex = re.search(pattern=pattern, string=string)

		if regex:
			return type_(regex.group(group_no))
		
		return None

	@staticmethod
	def _get_from_list(word_list, string):

		for el in word_list:
			if el in string:
				return el
		
		return None

	def _get_doors(self, info):
		return self._get_regex(r"([0-9])dr", info, type_=int)

	def _get_year(self, specs):
		return self._get_regex(r"\b([0-9]{4})\b", specs, type_=int)

	def _get_registration(self, specs):
		return self._get_regex(r"\(([0-9]{2}) reg\)", specs, type_=int)

	def _get_mileage(self, specs):
		
		miles = self._get_regex(r"\s([,0-9]+) miles\s", specs)

		return int(''.join(re.findall(r"[0-9]+", miles)))

	def _get_engine(self, specs):
		return self._get_regex(r"\b([\.0-9]+)L\b", specs, type_=float)

	def _get_bhp(self, specs):
		return self._get_regex(r"\b([0-9]+)(PS|HP|BHP)\b", specs, type_=int)

	def _get_transmission(self, specs):
		
		transmission_types = ["Automatic", "Manual"]

		return self._get_from_list(transmission_types, specs)

	def _get_owners(self, specs):
		return self._get_regex(r"\b([0-9]+) owner(s)?\b", specs, type_=int)

	def _get_fuel(self, specs):
		
		fuel_types = ["Petrol", "Diesel", "Electric", "Hybrid – Diesel/Electric Plug-in", "Hybrid – Petrol/Electric", "Hybrid – Petrol/Electric Plug-in"]

		return self._get_from_list(fuel_types, specs)

	def _get_body(self, specs):

		body_types = ["Coupe", "Convertible", "Estate", "Hatchback", "MPV", "Pickup", "SUV", "Saloon"]

		return self._get_from_list(body_types, specs)
	
	def _get_ulez(self, specs):
		return "ULEZ" in specs

	def get_car(self, article):

		# Get base car details
		model_name = article.find("h3", {"class": "product-card-details__title"}).text.strip()

		model_info = article.find("p", {"class": "product-card-details__subtitle"}).text.strip()

		car = {
			"model_name": model_name,
			"model_info": model_info,
			"doors": self._get_doors(model_info)
		}

		# Price indicator
		badges = article.find_all("li", {"class": "badge-group__item"})

		car['value_indicator'] = None
		car["write_off_category"] = None

		for badge in badges:

			if 'data-category' in badge.attrs:								

				if badge['data-category'].strip() == "writeOff":					
					car['write_off_category'] = badge.text.strip().split(' ')[1]
				else:
					car['value_indicator'] = badge.text.strip().lower()

		

		# Car id/url
		link = article.find("a", {"class": "tracking-standard-link"})["href"][: article.find("a", {"class": "tracking-standard-link"})["href"].find("?")]

		car['id'] = link.split('/')[-1]
		car["link"] = os.path.join("https://www.autotrader.co.uk", link)

		# Car price (convert to integer)
		price = article.find("div", {"class": "product-card-pricing__price"}).text.strip().split("£")[-1]

		car['price'] = int(''.join(price.split(',')))

		# Get key specifications
		key_spec_attributes = [
			"year",
			"registration",
			"mileage",
			"engine",
			"bhp",
			"transmission",
			"owners",
			"fuel",
			"body",
			"ulez"
		]
		
		key_specs = article.find("ul", {"class": "listing-key-specs"}).text
		
		for attr in key_spec_attributes:

			car[attr] = getattr(self, f'_get_{attr}')(key_specs)

		# Get Seller information
		car["seller"] = article.find("div", {"class": "product-card-seller-info__name-container"}).find("h3").text

		seller_info_li = article.find("ul", {"class": "product-card-seller-info__specs"}).find_all("li")

		car['location'] = seller_info_li[-1].find("span").text.strip()

		car['distance'] = self._get_regex(r"\(([0-9]+) mile(s)?\)", seller_info_li[-1].text.strip(), type_=int)

		if len(seller_info_li) == 2:

			car["seller_rating"] = float(seller_info_li[0].find("span").text.strip())
			car["seller_reviews"] = self._get_regex(r"([0-9]+) review(s)?", seller_info_li[0].find("a").text.strip(), type_=int)
		else:

			car["seller_rating"] = None
			car["seller_reviews"] = None

		return car

	def get_car_list_from_page(self, html):

		soup = BeautifulSoup(html, 'lxml')

		articles = soup.find_all("article", attrs={"data-standout-type":""})

		return [self.get_car(article) for article in articles]


	def search(self, reset_results=True, sort="Relevance", records_limit=None, max_attempts_per_page=5, verbose=False):		
		
		if reset_results:
			self.results = []

		sort_options = {
			"Relevance": "relevance",
			"Price (Lowest)": "price-asc",
			"Price (Highest)": "price-desc",
			"Distance": "distance",
			"Mileage": "mileage",
			"Age (Newest first)": "year-desc",
			"Age (Oldest first)": "year-asc",
			"Most recent": "datedesc"
		}


		if sort not in sort_options:
			raise ValueError(f"Sort option must be in {list(sort_options.keys())}")
		
		self.search_params["sort"] = sort_options[sort]
		self.search_params["search-results-price-type"] = "total-price"

		scraper = cloudscraper.create_scraper()
		
		page = 1
		n_cars = len(self.results)

		while True:

			try:
				
				self.search_params['page'] = page
				response = scraper.get(self.base_url, params=self.search_params)

				# Unsuccessful attempt
				if response.status_code != 200: 

					attempt = attempt + 1
					if attempt <= max_attempts_per_page:
						if verbose:
							print("Exception. Starting attempt #", attempt, "and keeping at page #", page)
					else:
						page += 1
						attempt = 1
						if verbose:
							print("Exception. All attempts exhausted for this page. Skipping to next page #", page)

				# Successful attempt
				else:

					car_list = self.get_car_list_from_page(response.json()['html'])

					if len(car_list) == 0:

						if verbose:
							print(f"Search complete - {n_cars} found in total")
						break

					self.results.extend(car_list)

					n_cars = n_cars + len(car_list)

					if verbose:
						print(f"Page {page}: {len(car_list)} cars found")

					# Increment year and reset relevant variables
					page += 1
					attempt = 1
					
				if n_cars > records_limit:

					self.results = self.results[:records_limit]

					if verbose:
						print(f"Search complete - {n_cars} found in total")
					
					break

			except KeyboardInterrupt:
				break

			except:
				traceback.print_exc()
				attempt = attempt + 1
				if attempt <= max_attempts_per_page:
					if verbose:
						print("Exception. Starting attempt #", attempt, "and keeping at page #", page)
				else:
					page += 1
					attempt = 1
					if verbose:
						print("Exception. All attempts exhausted for this page. Skipping to next page #", page)

		return self.results

	def to_dataframe(self):
		return pd.DataFrame.from_records(self.results)

	def to_csv(self, filename):
		df = self.to_dataframe()
		df.to_csv(filename, index=False)