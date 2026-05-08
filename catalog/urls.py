from django.urls import path, re_path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('search/suggest/', views.product_search_suggest_view, name='search_suggest'),
    path('', views.ProductListView.as_view(), name='product_list'),
    path('footer-products/', views.footer_products_feed_view, name='footer_products_feed'),
    path('vr-club-games/', views.vr_club_games_view, name='vr_club_games'),
    path('vr-club-games/add-custom-pack/', views.add_vr_club_custom_pack_to_cart_view, name='add_vr_club_custom_pack'),
    path('favorites/', views.favorite_list_view, name='favorites'),
    # slug с кириллицей: [\w-]+ вместо path slug (только ASCII)
    re_path(r'product/(?P<slug>[\w-]+)/', views.ProductDetailView.as_view(), name='product_detail'),
    re_path(r'bundle/(?P<slug>[\w-]+)/', views.BundleDetailView.as_view(), name='bundle_detail'),
    path('cart/', views.cart_page_view, name='cart'),
    path('cart/partial/', views.cart_partial, name='cart_partial'),
    path('cart/clear/', views.cart_clear_view, name='cart_clear'),
    path('cart/share/create/', views.cart_share_create_view, name='cart_share_create'),
    path('cart/share/add-all/', views.cart_share_add_all_view, name='cart_share_add_all'),
    path('cart/add-bundle/', views.add_bundle_to_cart_view, name='add_bundle_to_cart'),
    path('cart/add-game-pack/<int:game_pack_id>/', views.add_game_pack_to_cart_view, name='add_game_pack_to_cart'),
    path('cart/add/<int:product_id>/', views.add_to_cart_view, name='add_to_cart'),
    path('buy-now-bundle/', views.buy_now_bundle_view, name='buy_now_bundle'),
    path('buy-now-game-pack/<int:game_pack_id>/', views.buy_now_game_pack_view, name='buy_now_game_pack'),
    path('buy-now/<int:product_id>/', views.buy_now_product_view, name='buy_now_product'),
    path('cart/update/', views.cart_update_view, name='cart_update'),
    path('favorite/<int:product_id>/', views.toggle_favorite_view, name='toggle_favorite'),
    re_path(r'game-pack/(?P<slug>[\w-]+)/', views.GamePackDetailView.as_view(), name='game_pack_detail'),
]
