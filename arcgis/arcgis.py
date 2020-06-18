import logging

import requests

from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())


class SSLIgnoreHostnameAdapter(HTTPAdapter):
    """ Custom Requests pool manager with assert_hostname set to false

    This is used in the ArcGIS constructor if the user requests that ssl hostname checking
    be off for specific domains

    """
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       assert_hostname=False)


class ArcGISQueryError(Exception):
    """ A custom exception thrown when the API encounters an error in the query params """

    def __init__(self, json_dict, url):
        try:
            message = json_dict['error']['message']
        except KeyError:
            message = 'Unknown error'
        super(ArcGISQueryError, self).__init__(message)
        self.json = json_dict
        self.url = url


class ArcGIS:
    """
    A class that can download a layer from a map in an
    ArcGIS web service and convert it to something useful,
    like GeoJSON.

    Usage:

    >>> import arcgis
    >>> source = "http://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/USA_Congressional_Districts/FeatureServer"
    >>> arc = arcgis.ArcGIS(source)
    >>> layer_id = 0
    >>> shapes = arc.get(layer_id, "STATE_ABBR='IN'")

    This assumes you've inspected your ArcGIS services endpoint to know what to look for.
    ArcGIS DOES publish json files enumerating the endpoints you can query, so autodiscovery
    could be possible further down the line.

    """
    def __init__(self, url, geom_type=None, object_id_field="OBJECTID",
                 username=None, password=None,
                 token_url='https://www.arcgis.com/sharing/rest/generateToken',
                 referer='http://www.arcgis.com',
                 server_ssl_cert=None,
                 client_ssl_cert=None,
                 ssl_ignore_hostname=None):
        self.url = url
        self.object_id_field = object_id_field
        self._layer_descriptor_cache = {}
        self.geom_type = geom_type
        self._geom_parsers = {
            'esriGeometryPoint': self._parse_esri_point,
            'esriGeometryMultipoint': self._parse_esri_multipoint,
            'esriGeometryPolyline': self._parse_esri_polyline,
            'esriGeometryPolygon': self._parse_esri_polygon
        }

        self.username = username
        self.password = password
        self.referer = referer
        self.token_url = token_url
        self._token = None

        self.session = Session()
        if ssl_ignore_hostname:
            # TODO: Ignore multiple hostnames
            self.session.mount(ssl_ignore_hostname, SSLIgnoreHostnameAdapter())
        if server_ssl_cert:
            self.session.verify = server_ssl_cert
        if client_ssl_cert:
            self.session.cert = client_ssl_cert
        self.session.headers.update({'referer': self.referer})

    def _build_request(self, layer):
        return urljoin(self.url, layer)

    def _build_query_request(self, layer):
        return urljoin(self._build_request(layer), "query")

    def _parse_esri_point(self, geom):
        return {
            "type": "Point",
            "coordinates": [
                geom.get('x'),
                geom.get('y')
            ]
        }

    def _parse_esri_multipoint(self, geom):
        return {
            "type": "MultiPoint",
            "coordinates": geom.get('points')
        }

    def _parse_esri_polyline(self, geom):
        return {
            "type": "MultiLineString",
            "coordinates": geom.get('paths')
        }

    def _parse_esri_polygon(self, geom):
        return {
            "type": "Polygon",
            "coordinates": geom.get('rings')
        }

    def _determine_geom_parser(self, type):
        return self._geom_parsers.get(type)

    def esri_to_geojson(self, obj, geom_parser):
        return {
            "type": "Feature",
            "properties": obj.get('attributes'),
            "geometry": geom_parser(obj.get('geometry')) if obj.get('geometry') else None
        }

    def get_json(self, layer, where="1 = 1", fields=[], count_only=False, srid='4326',
                 input_geom_type=None, input_geom=None, input_srid=None, spatial_rel=None):
        """
        Gets the JSON file from ArcGIS
        """
        params = {
            'where': where,
            'outFields': ", ".join(fields),
            'returnGeometry': True,
            'outSR': srid,
            'f': "pjson",
            'orderByFields': self.object_id_field,
            'returnCountOnly': count_only
        }

        geom_filter_params = {
            'inSR': input_srid,
            'geometryType': input_geom_type,
            'geometry': input_geom,
            'spatialRel': spatial_rel
        }

        spatial_filter_params = [input_srid, input_geom_type, input_geom, spatial_rel]
        if all(spatial_filter_params):
            params.update(geom_filter_params)

        if not all(spatial_filter_params) and any(spatial_filter_params):
            logger.warning('Ignoring spatial filter - not all parameters supplied')

        if self.token:
            params['token'] = self.token
        if self.geom_type:
            params.update({'geometryType': self.geom_type})
        response = self.session.get(self._build_query_request(layer), params=params)
        jsobj = response.json()
        if jsobj.get('error', None) is not None:
            raise ArcGISQueryError(jsobj, response.url)
        return jsobj

    def get_descriptor_for_layer(self, layer):
        """
        Returns the standard JSON descriptor for the layer. There is a lot of
        usefule information in there.
        """
        if not layer in self._layer_descriptor_cache:
            params = {'f': 'pjson'}
            if self.token:
                params['token'] = self.token
            response = self.session.get(self._build_request(layer), params=params)
            self._layer_descriptor_cache[layer] = response.json()
        return self._layer_descriptor_cache[layer]

    def enumerate_layer_fields(self, layer):
        """
        Pulls out all of the field names for a layer.
        """
        descriptor = self.get_descriptor_for_layer(layer)
        return [field['name'] for field in descriptor['fields']]

    def get(self, layer, where="1 = 1", fields=[], count_only=False, srid='4326',
                 input_geom_type=None, input_geom=None, input_srid=None, spatial_rel=None):
        """
        Gets a layer and returns it as honest to God GeoJSON.

        WHERE 1 = 1 causes us to get everything. We use OBJECTID in the WHERE clause
        to paginate, so don't use OBJECTID in your WHERE clause unless you're going to
        query under 1000 objects.
        """
        base_where = where
        # By default we grab all of the fields. Technically I think
        # we can just do "*" for all fields, but I found this was buggy in
        # the KMZ mode. I'd rather be explicit.
        fields = fields or self.enumerate_layer_fields(layer)

        jsobj = self.get_json(layer, where, fields, count_only, srid,
                              input_geom_type, input_geom, input_srid, spatial_rel)

        # Sometimes you just want to know how far there is to go.
        if count_only:
            return jsobj.get('count')

        # If there is no geometry, we default to assuming it's a Table type
        # data format, and we dump a simple (non-geo) json of all of the data.
        if not jsobj.get('geometryType', None):
            return self.getTable(layer, where, fields, jsobj=jsobj)

        # From what I can tell, the entire layer tends to be of the same type,
        # so we only have to determine the parsing function once.
        geom_parser = self._determine_geom_parser(jsobj.get('geometryType'))

        features = []
        # We always want to run once, and then break out as soon as we stop
        # getting exceededTransferLimit.
        while True:
            features += [self.esri_to_geojson(feat, geom_parser) for feat in jsobj.get('features')]
            if jsobj.get('exceededTransferLimit', False) == False:
                break
            # If we've hit the transfer limit we offset by the last OBJECTID
            # returned and keep moving along.
            where = "%s > %s" % (self.object_id_field, features[-1]['properties'].get(self.object_id_field))
            if base_where != "1 = 1" :
                # If we have another WHERE filter we needed to tack that back on.
                where += " AND %s" % base_where
            jsobj = self.get_json(layer, where, fields, count_only, srid,
                                  input_geom_type, input_geom, input_srid, spatial_rel)


        return {
            'type': "FeatureCollection",
            'features': features
        }

    def getTable(self, layer, where="1 = 1", fields=[], jsobj=None):
        """
        Returns JSON for a Table type. You shouldn't use this directly -- it's
        an automatic falback from .get if there is no geometry
        """
        base_where = where
        features = []
        # We always want to run once, and then break out as soon as we stop
        # getting exceededTransferLimit.
        while True:
            features += [feat.get('attributes') for feat in jsobj.get('features')]
            # There isn't an exceededTransferLimit?
            if len(jsobj.get('features')) < 1000:
                break
            # If we've hit the transfer limit we offset by the last OBJECTID
            # returned and keep moving along.
            where = "%s > %s" % (self.object_id_field, features[-1].get(self.object_id_field))
            if base_where != "1 = 1" :
                # If we have another WHERE filter we needed to tack that back on.
                where += " AND %s" % base_where
            jsobj = self.get_json(layer, where, fields)
        return features

    def getMultiple(self, layers, where="1 = 1", fields=[], srid='4326', layer_name_field=None):
        """
        Get a bunch of layers and concatenate them together into one. This is useful if you
        have a map with layers for, say, every year named stuff_2014, stuff_2013, stuff_2012. Etc.

        Optionally, you can stuff the source layer name into a field of your choosing.

        >>> arc.getMultiple([0, 3, 5], layer_name_field='layer_src_name')

        """
        features = []
        for layer in layers:
            get_fields = fields or self.enumerate_layer_fields(layer)
            this_layer = self.get(layer, where, get_fields, False, srid).get('features')
            if layer_name_field:
                descriptor = self.get_descriptor_for_layer(layer)
                layer_name = descriptor.get('name')
                for feature in this_layer:
                    feature['properties'][layer_name_field] = layer_name
            features += this_layer
        return {
            'type': "FeatureCollection",
            'features': features
        }

    @property
    def token(self):
        if self._token is None and self.username and self.password:
            token_params = {
                'f': 'json',
                'username': self.username,
                'password': self.password,
                'expiration': 60,
                'client': 'referer',
                'referer': self.referer
            }
            try:
                response = self.session.post(self.token_url, data=token_params).json()
                self._token = response['token']
            except requests.exceptions.Timeout:
                print('Connection to {0} timed out'.format(self.token_url))
                raise
            except requests.exceptions.ConnectionError:
                print('Unable to connect to host at {0}'.format(self.token_url))
                raise
            except requests.exceptions.URLRequired:
                print('Invalid URL - {0}'.format(self.token_url))
                raise
            except KeyError:
                print('Error retrieving token - {0}'.format(response))
                raise

        return self._token



def urljoin(*args):
    """
    There's probably a better way of handling this.
    """
    return "/".join(map(lambda x: str(x).rstrip('/'), args))
