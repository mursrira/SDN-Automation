from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.index, name='index'),
url(r'^logout$',views.logout,name='logout'),
url(r'^login$', views.login, name='login'),
#url(r'^ShowCurrentLspPath$', views.currentPath, name='currentPath'),
url(r'^currentPath$', views.ajaxCurrentPath, name='ajaxCurrentPath'),
url(r'^getallLsp$', views.ajaxgetallLsp, name='ajaxgetallLsp'),
url(r'^getoptmisedPath$', views.ajaxgetoptPath, name='ajaxgetoptPath'),
url(r'^getShowConfig$', views.ajaxShowConfig, name='ajaxShowConfig'),
url(r'^pushApplyConfig$', views.ajaxApplyConfig, name='ajaxApplyConfig'),
]

