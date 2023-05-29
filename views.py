from datetime import datetime
import logging
import re
from typing import Any, Dict, List
from django.views.generic import TemplateView
from django.db.models import Q

from bs4 import BeautifulSoup as BS4
import requests
from urllib.parse import urlparse

from pp.models import Category, Goods
from pp.utils.cleaners import text_cleaner


__all__ = ['P1']


class P1(TemplateView):
    """
    Класс реализует сбор категорий их страниц и товаров с них.\n
    ** ВНИМАНИЕ!!! Работу с изображениями смотри в основной части на PHP
    """
    site_host = None
    site_url = 'https://www.gryazi.net/catalog/'
    site_categories_url = 'https://www.gryazi.net/catalog/dezinfitsiruyushchie_sredstva/'
    categories_list = []
    main_categories_list = []
    run_datetime = None
    template_name = 'pp/index.html'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        host_data = urlparse(self.site_url)
        host = f'{host_data.scheme}://{host_data.netloc}'
        self.site_host = host
        self.run_datetime = int(datetime.now().timestamp())
        self.categories_list = self.collect_categories()
        self.main_categories_list = self.get_main_categories()

    def collect_categories(self) -> list[dict]:
        """ Return category URLS from site URL """
        bs4_soup = self.get_page(self.site_categories_url)
        if bs4_soup is not None:
            categories = [{
                'name': 'Технология Чистоты',
                'full_url': self.make_full_url('catalog'),
                'url': self.get_category_url('catalog'),
                'parent': None,
                'object': self.get_category_object({
                    'c_name__iexact': 'Технология Чистоты',
                    'c_id__gte': 2273,
                }),
            }]

            # Select categories through method self.get_soup_objects
            for x in self.get_soup_objects(bs4_soup, '.d-xl-block > .b-category-menu > .__list > li a'):
                href = text_cleaner(x.get('href'))
                name = text_cleaner(x.text)
                category_data = {
                    'name': name,
                    'full_url': self.make_full_url(href),
                    'url': self.get_category_url(href),
                    'parent': self.get_category_url(href, get_parent=True),
                    'object': self.get_category_object({
                        'c_name__iexact': name,
                        'c_id__gte': 2273,
                    }),
                }
                categories.append(category_data)

                logging.debug( f"COLLECT CAT {category_data.get('full_url','---')}" )
                cat_soup = self.get_page(category_data.get('full_url'))
                if cat_soup:
                    for sub_cat in self.get_soup_objects(cat_soup, '.b-tags.--cats a'):
                        href = text_cleaner(sub_cat.get('href'))
                        name = text_cleaner(sub_cat.text)
                        category_data = {
                            'name': name,
                            'full_url': self.make_full_url(href),
                            'url': self.get_category_url(href),
                            'parent': self.get_category_url(href, get_parent=True),
                            'object': self.get_category_object({
                                'c_name__iexact': name,
                                'c_id__gte': 2273,
                            }),
                        }
                        logging.debug( f"     SUBCAT {category_data.get('url','---')}" )
                        categories.append(category_data)

            for x in categories:
                x_obj = x.get('object')
                logging.debug(x.get('url') +' '+ x.get('parent'))
                if( x.get('parent') == None ):
                    if not x_obj.pk:
                        x_obj.save()
                        pass
                else:
                    for parent in categories:
                        logging.debug( '    ' + parent.get('name') )
                        p_obj = parent.get('object')
                        if x.get('parent') == parent.get('url'):
                            logging.debug( '        '+ parent.get('url') )
                            if( p_obj.pk ):
                                x_obj.c_parent = p_obj.pk
                                x_obj.save()
                            break

            return categories
        else:
            return []
    
    def collect_pagesgoods(self, cat_url:str = None, pages:int = None) -> list[Goods]:
        """ Собираем объекты товаров с каждой страницы категории в список """
        goods_list = []
        # pages = 1
        if pages and cat_url:
            logging.debug( 'CAT >>'+ cat_url )
            urls = [cat_url + f'?PAGEN_2={(x+1)}' for x in range(pages)]
            for u in urls:
                logging.debug( '  P >>'+ u )
                bs4_soup = self.get_page(u)
                for url in self.get_soup_objects(bs4_soup, '.b-list-item .__name'):
                    good_url = url.get('href')
                    # logging.debug( '  G ::'+ good_url )
                    goods_list.append(
                        self.collect_good(
                            self.make_full_url(good_url)
                        )
                    )
        return goods_list

    def collect_good(self, url: str = None) -> Goods:
        """ Собираем параметры по Goods со страницы в объект Goods """
        if url:
            good = {
                'g_date': self.run_datetime
            }
            bs4_soup = self.get_page(url)    
    
            g_img = self.get_soup_objects(bs4_soup, '.b-card-item .b-card-img')
            if g_img:
                g_img = g_img[0].get('href', None)
                g_img = self.make_full_url(g_img)
                good.update({'g_img':g_img})
            
            g_model = self.get_soup_objects(bs4_soup, '.b-card-item h1.h1')
            if g_model:
                g_model = g_model[0].text
                good.update({'g_model':g_model})
            
            vendorcode = self.get_soup_objects(bs4_soup, '.b-card-item .--text-gray')
            if vendorcode:
                vendorcode = vendorcode[0].text
                vendorcode = vendorcode.replace('Артикул: ', '')
                vendorcode = f'({vendorcode}) gryazi'
                good.update({'vendorcode':vendorcode})

            breadcrumbs_list = self.get_soup_objects(bs4_soup, '.b-bread ul li a')
            if breadcrumbs_list:
                href = breadcrumbs_list[-1]
                href_parts = [x for x in str(href.get('href')).split('/') if x]
                
                if href_parts:
                    cat_url = href_parts[-1]
                    for cat in self.categories_list:
                        if cat_url == cat.get('url'):
                            good.update({'g_category': cat.get('object').c_id})
                    # if not good.get('g_category', None):
                        # logging.debug( 'NOT CAT ::'+ cat_url )
                            
            g_details = self.get_soup_objects(bs4_soup, '.bg-card-item .mb-md-5')
            if g_details:
                g_details = g_details[0].text
                good.update({'g_details':g_details})

            in_stock = self.get_soup_objects(bs4_soup, '.b-card-item .b-avail')
            if in_stock:
                good.update({'in_stock':1})
            else:
                good.update({'in_stock':0})

            params = self.get_soup_objects(bs4_soup, '.b-table-params tbody tr')
            params_array = {}
            for p_row in params:
                cols = self.get_soup_objects(p_row, 'td')
                name = cols[0].text.strip()
                value = cols[1].text.strip()
                params_array[name] = value
            
            if params_array:
                good.update({
                    'parameters': self.get_params_text(params_array)
                })

            g_price = self.get_soup_objects(bs4_soup, '.b-card-item .js-card-item .b-price span')
            g_price_old = self.get_soup_objects(bs4_soup, '.b-card-item .js-card-item .b-price .__old')
            price = 0
            if g_price_old:
                price = g_price_old[0].text
            elif g_price:
                price = g_price[0].text
            else:
                price = 0
            price = price.replace('руб.', '')
            price = re.sub(r"[^\d\.\,]", "", price)
            price = price if price else 0

            good.update({
                'g_price': price,
                'g_visible': 1,
            })

        return Goods(**good)

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update({
            'categories': self.categories_list,
            'main_categories': self.main_categories_list,
        })
        return context

    def get_page(self, url) -> (BS4 | None):
        """ Получаем код страницы и загружаем в BS4 """
        r = requests.get(url)
        bs4_soup = self.get_bs4(r.text, r.status_code)
        return bs4_soup

    def get_bs4(self, html_text: str = None, status_code: int = 200) -> (BS4 | None):
        """ Получаем BS4 из текста страницы если статус 200 иначе отдаём None """
        if(html_text and status_code == 200):
            return BS4(html_text, 'html.parser')
        else:
            return None

    def get_main_categories(self) -> list[dict]:
        """ Фильтруем категории для получения основных категорий, собираем количество страниц для них """
        for item in self.categories_list:
            if item.get('parent') == 'catalog':
                url = item.get('full_url')
                bs4_soup = self.get_page(url)
                if bs4_soup is not None:
                    paginator_links = self.get_soup_objects(bs4_soup, '.bx-pagination-container ul li > a')
                    last_page_num = None
                    for link in paginator_links:
                        if str(link.text).isnumeric():
                            last_page_num = int(link.text)
                    item['pages'] = last_page_num
                    item['pages_goods'] = self.collect_pagesgoods(item.get('full_url'), last_page_num)

                    # SAVE GOODS
                    for good in item['pages_goods']:
                        good.save()

        return [x for x in self.categories_list if x.get('parent') == 'catalog']

    def make_full_url(self, url: str = '') -> str:
        """ Формируем полный URL для работы парсера """
        if url:
            if self.site_host in url:
                return url
            else:
                if url[0] == '/':
                    url = url[1:]
                return f'{self.site_host}/{url}'
        else:
            return self.site_host
    
    def get_soup_objects(self, bs4_soup, selector):
        """ Фильтр объектов BS4 """
        return bs4_soup.select(selector)

    def get_category_url(self, href: str = None, get_parent: bool = False) -> (str | None):
        """ Получаем alias категории, либо её родителя """
        if href:
            href_data = [x for x in href.split('/') if x]
            if( not get_parent ):
                return href_data[-1]
            else:
                if len(href_data) > 1:
                    return href_data[-2]
        else:
            return None

    def get_category_object(self, params: dict = None, exclude_params: list = ['_id', 'id', 'pk']) -> Category:
        """ Проверяем наличие категорий по фильтру. Возвращаем найденный объект либо существующий """
        Q_FILTER = Q()
        for key in params.keys():
            if key and params.get(key, None):
                Q_FILTER.add(
                    Q(**{key: params[key]}), 
                    Q.AND
                )
        obj = Category.objects.filter(Q_FILTER).first()
        
        if not obj:
            # Чистим селекторы "__" такие как  "__gte", убираем _id/id из параметров
            params = {
                key.split('__')[0]: params[key] 
                for key in params 
                if not any([
                    x in key for x in exclude_params
                ])
            } 
        
        return obj if obj else Category(**params)

    def get_params_text(self, params: dict = {}) -> (str | None):
        """ Формируем объект параметров товара """
        params_str = '<p>'
        for key, value in params.items():
            params_str += ' -- '.join([
                key, value
            ]) + "<br>"
        params_str += '</p>'
        params_str = params_str.replace(': -- ', ' -- ')
        
        return params_str if params_str != '<p></p>' else None


class PageDetailView(TemplateView):
    model_g = Goods
    model_c = Category
    template_name = "pp/detail.html"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update({
            'goods': self.model_g.objects.select_related('g_category').filter(
                g_visible=True,
            ),
            'categories': self.model_c.objects.prefetch_related('goods').filter(
                c_visible=True,
            )
        })
        return context
    