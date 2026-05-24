"""Catalog test package."""

from unittest import TestSuite


ORDERED_TEST_CASES = [
    'catalog.tests.test_game_packs.ClubFormatNormalizationTest',
    'catalog.tests.test_game_packs.VRClubGamesB2BTest',
    'catalog.tests.test_catalog_pages.CatalogSearchTest',
    'catalog.tests.test_catalog_pages.CatalogSearchSuggestTest',
    'catalog.tests.test_regressions.SpamProtectionHelperTest',
    'catalog.tests.test_regressions.CatalogSortLinksEscapingRegressionTest',
    'catalog.tests.test_regressions.PublicLocationCleanupRegressionTest',
    'catalog.tests.test_import_export.SeedStarvrPacksCommandTest',
    'catalog.tests.test_admin.ProductAdminGamePackMirrorTest',
    'catalog.tests.test_import_export.NormalizeGameSectionsMigrationTest',
    'catalog.tests.test_game_packs.GamePackDetailRegressionTest',
    'catalog.tests.test_product_pages.VariantGalleryAndCatalogCardsTest',
    'catalog.tests.test_content_blocks.ProductContentBlocksTest',
    'catalog.tests.test_filters.CatalogSectionFilterTest',
    'catalog.tests.test_filters.CatalogPriceBoundsTest',
    'catalog.tests.test_filters.CatalogManagedFiltersTest',
    'catalog.tests.test_filters.CatalogFilterAuditTest',
    'catalog.tests.test_filters.CatalogFilterAutomationTest',
    'catalog.tests.test_catalog_pages.HomeFeaturedProductsTest',
    'catalog.tests.test_catalog_pages.CatalogMenuCacheTest',
    'catalog.tests.test_regressions.RequestScopedCartServicesCacheTest',
    'catalog.tests.test_regressions.LegalPagesAndLinksTest',
    'catalog.tests.test_regressions.LegalConsentFormsAndViewsTest',
    'catalog.tests.test_catalog_pages.ServicesPageTest',
    'catalog.tests.test_regressions.PublicLeadFormsSpamProtectionTest',
    'catalog.tests.test_catalog_pages.FavoriteTest',
    'catalog.tests.test_catalog_pages.CartTest',
    'catalog.tests.test_product_pages.ProductRecommendationsTest',
    'catalog.tests.test_catalog_pages.FooterProductsFeedTest',
    'catalog.tests.test_yml_feed.VrAttractionsYmlFeedTest',
    'catalog.tests.test_yml_feed.VrAttractionsYmlFeedPicturesTest',
    'catalog.tests.test_yml_feed.VrAttractionsYmlFeedHelpersTest',
    'catalog.tests.test_yml_feed.VrAttractionsYmlFeedMissingSectionTest',
    'catalog.tests.test_catalog_pages.SeoFilesTest',
    'catalog.tests.test_catalog_pages.CompareRemovalTest',
    'catalog.tests.test_admin.AdminRestoreSecurityTest',
    'catalog.tests.test_import_export.AdminProductExportTest',
    'catalog.tests.test_import_export.CatalogJsonImportServiceTest',
    'catalog.tests.test_import_export.CatalogJsonImportWorkflowTest',
    'catalog.tests.test_admin.AdminImportJsonSecurityTest',
    'catalog.tests.test_game_packs.StandaloneGamePackCatalogTest',
    'catalog.tests.test_catalog_pages.DigitalCatalogSectionIaTest',
]


def load_tests(loader, tests, pattern):
    suite = TestSuite()
    for test_case in ORDERED_TEST_CASES:
        suite.addTests(loader.loadTestsFromName(test_case))
    return suite
