import ee
import datetime
from flask import jsonify
import functions_framework

BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7']

def maskL8sr(image):
  cloudShadowBitMask = ee.Number(2).pow(3).int()
  cloudsBitMask = ee.Number(2).pow(5).int()
  qa = image.select('pixel_qa')
  mask = qa.bitwiseAnd(cloudShadowBitMask).eq(0).And(
    qa.bitwiseAnd(cloudsBitMask).eq(0))
  return image.updateMask(mask).select(BANDS).divide(10000)

@functions_framework.http
def main(request):

    #get the request body
    request_json = request.get_json()
    bucket = request_json['input']
    #get date
    date_str = datetime.datetime.today().strftime('%Y-%m-%d')
    #output file name
    file_name_prefix = date_str + '/download/image_'
    
    #initialize earth engine using json key for service account
    service_account = 'ee-test-deploy@test-ee-deploy.iam.gserviceaccount.com'
    credentials = ee.ServiceAccountCredentials(service_account, 'sa-private-key.json')
    ee.Initialize(credentials)

    #aoi
    EXPORT_REGION = ee.Geometry.Rectangle([-122.7, 37.3, -121.8, 38.00])
    #EXPORT_REGION = ee.Geometry.Polygon([[[-122.6465380286344, 39.04658449307978],[-122.6465380286344, 37.24966450365536],[-119.4605028723844, 37.24966450365536],[-119.4605028723844, 39.04658449307978]]])
    #EXPORT_REGION = ee.Geometry.Polygon([[[-125.30193824768067, 45.516811272883174], [-125.30193824768067, 37.049558686931945],[-117.96307106018067, 37.049558686931945],[-117.96307106018067, 45.516811272883174]]])
    #get current date and convert to ee.Date
    end_date = ee.Date(date_str)
    start_date = end_date.advance(-1,'year')
  
    # The image input data is cloud-masked median composite for the last year.
    image = ee.ImageCollection('LANDSAT/LC08/C01/T1_SR')\
        .filterDate(start_date, end_date)\
        .map(maskL8sr)\
        .median()
    
    # Specify patch and file dimensions.
    #max file size is 100mb
    image_export_options = {
    'patchDimensions': [256, 256],
    'maxFileSize': 100000000,
    'compressed': True
    }

    # Setup the task.
    image_task = ee.batch.Export.image.toCloudStorage(
    image=image,
    description='image_export',
    fileNamePrefix=file_name_prefix,
    bucket=bucket,
    maxPixels=1e12,
    scale=30,
    fileFormat='TFRecord',
    region=EXPORT_REGION.toGeoJSON()['coordinates'],
    formatOptions=image_export_options,
    )

    image_task.start()
    
    output = {'folder': 'gs://'+bucket+'/'+date_str,'task':image_task.name}
    return jsonify(output)