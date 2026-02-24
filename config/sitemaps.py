from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from catalog.models import Product, ProductBundle


class StaticViewSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return [
            'home',
            'arenda',
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

