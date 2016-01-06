import json
import unittest
from arcgis import ArcGIS

class ArcGISTest(unittest.TestCase):
    """
    Make sure we didn't break stuff
    """
    def test_count(self):
        districts = ArcGIS("http://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/USA_Congressional_Districts/FeatureServer")
        count = districts.get(0, count_only=True)
        self.assertEqual(count, 437)
        count = districts.get(0, where="STATE_ABBR = 'PA'", count_only=True)
        self.assertEqual(count, 18)

    def test_features(self):
        districts = ArcGIS("http://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/USA_Congressional_Districts/FeatureServer")
        features = districts.get(0, "STATE_ABBR = 'IN'")
        # Make sure we have all of the actual congressional
        # district shapes for Indiana.
        self.assertEqual(len(features.get('features')), 9)
        # Make sure they're polygons
        self.assertEqual(features.get('features')[0].get('geometry').get('type'), "Polygon")
        # Make sure it's valid json when we dump it
        self.assertTrue(features == json.loads(json.dumps(features)))
        # Make sure a value that should be there is ther.
        self.assertEqual(features.get('features')[0].get('properties').get('STATE_ABBR'), 'IN')

    def test_field_filter(self):
        districts = ArcGIS("http://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/USA_Congressional_Districts/FeatureServer")
        # How many fields are there in the layer?
        num_fields = districts.enumerate_layer_fields(0)
        self.assertEqual(len(num_fields), 12)
        # We should only have one property, OBJECTID.
        features = districts.get(0, where="STATE_ABBR = 'IN'", fields=['OBJECTID'])
        self.assertEqual(len(features.get('features')[0].get('properties')), 1)

    def test_multiple(self):
        districts = ArcGIS("http://sampleserver1.arcgisonline.com/ArcGIS/rest/services/TaxParcel/AssessorsValueAnalysis/MapServer")
        # Gets 114th and 113th congressional districts for hawaii.
        features = districts.getMultiple([4, 5], where="NOSALE>0", fields='OBJECTID,NOSALE')
        self.assertEqual(len(features.get('features')), 5)

    def test_spatial_query(self):
        districts = ArcGIS("http://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/USA_Congressional_Districts/FeatureServer")
        full_count = districts.get(0, count_only=True)
        self.assertEqual(full_count, 437)

        input_geom_type = 'esriGeometryPolygon'
        # Roughly PA
        input_geom = '{"rings":[[[-80.70556640625,39.223742741391305],[-80.70556640625,42.407234661551875],[-75.311279296875,42.407234661551875],[-75.311279296875,39.223742741391305],[-80.70556640625,39.223742741391305]]],"hasZ":false,"hasM":false}'
        input_srid = '4326'
        spatial_rel = 'esriSpatialRelContains'
        filtered_count = districts.get(0, where="STATE_ABBR = 'PA'", count_only=True, input_geom_type=input_geom_type, input_geom=input_geom, input_srid=input_srid, spatial_rel=spatial_rel)
        self.assertEqual(filtered_count, 10)
        self.assertNotEqual(full_count, filtered_count)

if __name__ == '__main__':
    unittest.main()
