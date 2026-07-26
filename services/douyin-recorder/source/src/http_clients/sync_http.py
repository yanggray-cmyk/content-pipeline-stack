# -*- coding: utf-8 -*-
import gzip
import urllib.parse
import urllib.error
import requests
import ssl
import json
import urllib.request

no_proxy_handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(no_proxy_handler)

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
OptionalStr = str | None
OptionalDict = dict | None


