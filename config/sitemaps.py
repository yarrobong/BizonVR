from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from catalog.models import Product, ProductBundle
from config.solution_landings import get_solution_landings


class StaticViewSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return [
            'home',
            'arenda',
            'conference_attractions',
            'uslugi',
            'contacts',
            'privacy',
            'oferta',
            'user_agreement',
            'pd_consent',
            'cookies_policy',
            'sales_terms',
            'service_request_terms',
            'catalog:product_list',
        ]

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Product.objects.filter(is_active=True).order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at


class BundleSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return ProductBundle.objects.all().order_by('id')


class SolutionsHubSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.75

    def items(self):
        return ['solutions_index']

    def location(self, item):
        return reverse(item)


class SolutionLandingSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return get_solution_landings(include_in_sitemap=True)

    def location(self, item):
        return reverse('solution_landing', kwargs={'slug': item.slug})
