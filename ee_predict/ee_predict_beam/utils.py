from typing import List, Optional

import apache_beam as beam
from apache_beam import coders
from apache_beam.io.filesystem import CompressionTypes
from apache_beam.io.iobase import Read
from apache_beam.transforms import PTransform
from apache_beam.io.tfrecordio import _TFRecordUtil
from apache_beam.io.tfrecordio import _TFRecordSource

from apache_beam.ml.inference.base import ModelHandler

import tensorflow as tf
import numpy as np

#import json

BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7']
PATCH_DIMENSIONS_FLAT = [256*256,1]
FEATURES = {
    band: tf.io.FixedLenFeature(PATCH_DIMENSIONS_FLAT, dtype=tf.float32)
    for band in BANDS
}

#beam model hanlder calss does the work of efficiently load our model onto workers and making rpedicitons
class LandCoverModel(ModelHandler[np.ndarray, np.ndarray, tf.keras.Model]):
    def __init__(
        self,
        tfmodel:str) -> None:
        super().__init__()
        self.tfmodel=tfmodel

    def load_model(self) -> tf.keras.Model:
        return tf.keras.models.load_model(self.tfmodel)

    def batch_elements_kwargs(self):
        return {'max_batch_size': 1}

    def run_inference(
        self, 
        batch,
        model: tf.keras.Model,
        inference_args: Optional[dict] = None,
        ):  
        batch=np.stack(batch).squeeze(axis=0)

        probabilities = model.predict(batch)
        probabilities = probabilities.astype(np.float64)
        return probabilities[None,:,:]   
    
#sublcass the deafult _TFRecordSource to return the shard and patch number as well the decorded record
class KeyedTFRecordSource(_TFRecordSource):
    def __init__(self, file_pattern, coder, compression_type, validate):
        super(KeyedTFRecordSource, self).__init__(file_pattern, coder, compression_type, validate)
    
    def read_records(self, file_name, offset_range_tracker):
        if offset_range_tracker.start_position():
            raise ValueError(
                'Start position not 0:%s' % offset_range_tracker.start_position())

        current_offset = offset_range_tracker.start_position()
        with self.open_file(file_name) as file_handle:
            while True:
                if not offset_range_tracker.try_claim(current_offset):
                    raise RuntimeError('Unable to claim position: %s' % current_offset)
                record = _TFRecordUtil.read_record(file_handle)
                if record is None:
                    return  # Reached EOF
                else:
                    current_offset += _TFRecordUtil.encoded_num_bytes(record)
                    yield (file_name, current_offset, self._coder.decode(record))
                
#read from tfrecord and return a PCollection of (file_name, patch, record)                
class KeyedReadFromTFRecord(PTransform):
    def __init__(
        self,
        file_pattern,
        coder=coders.BytesCoder(),
        compression_type=CompressionTypes.AUTO,
        validate=True):
        super(KeyedReadFromTFRecord, self).__init__()
        self._source = KeyedTFRecordSource(
            file_pattern, coder, compression_type, validate)

    def expand(self, pvalue):
        return pvalue.pipeline | Read(self._source)

#splits the default exported ee tfrecord file name to get the shard number
def file_path_key(file_path):
    return file_path.split('_')[-1].split('.')[0]

#transpose each key in the data
def transpose_per_key(data_key, data_dict):
    for key, value in data_dict.items():
        data_dict[key] = tf.transpose(value)
        data_dict[key] = tf.transpose(value)
    return data_key, data_dict
    
def add_ndvi(data_key, data_dict):
    data_dict['NDVI'] = (data_dict['B5'] - data_dict['B4'])/(data_dict['B5'] + data_dict['B4'])
    return data_key, data_dict    
 
#split patch to array of pixels   
def break_up_patch(x):
    key, data_dict = x
    return [(f'{key},{i}', pixel_dict) 
            for i, pixel_dict 
            in enumerate(tf.data.Dataset.from_tensor_slices(data_dict))
           ]
#parse the patch key to an int    
def parse_key(patch_key, patch_data):
    str_key = str(patch_key)
    split_key = str_key.split(',')
    # need to convert these to integers so sorting works correctly
    # 101 comes before 11 if sorted alphanumerically which we don't 
    # want
    actual_key = [split_key[0], int(split_key[1])]
    return actual_key, patch_data
    
#create tfrecord example    
def create_example(patch_key, patch_data):
    patch = [[], [], [], []]

    for pixel_data in patch_data:
      
      patch[0].append(tf.argmax(pixel_data, 1)[0])
      patch[1].append(pixel_data[0][0])
      patch[2].append(pixel_data[0][1])
      patch[3].append(pixel_data[0][2])

    example = tf.train.Example(
      features=tf.train.Features(
        feature={
          'prediction': tf.train.Feature(
              int64_list=tf.train.Int64List(
                  value=patch[0])),
          'bareProb': tf.train.Feature(
              float_list=tf.train.FloatList(
                  value=patch[1])),
          'vegProb': tf.train.Feature(
              float_list=tf.train.FloatList(
                  value=patch[2])),
          'waterProb': tf.train.Feature(
              float_list=tf.train.FloatList(
                  value=patch[3])),
        }
      )
    )
    return (patch_key, example)

#write to tfrecords
class MapWriteToTFRecord(beam.DoFn):
    def process(self, data, output_dir):
        file_key = data[0]
        file_key = file_key.rsplit('/')[-1]
        file_data = data[1]
        file_data = sorted(file_data, key=lambda patch_data: patch_data[0])
        #options = tf.io.TFRecordOptions(compression_type='GZIP')
        writer = tf.io.TFRecordWriter(f'{output_dir}{file_key}.tfrecord')#, options=options)
        for _, patch_example in file_data:
            writer.write(patch_example.SerializeToString())
        writer.close()
        return [f'{output_dir}{file_key}']
    
#def jsonify_data(key, data):
#    data = [
#       [float(element) for element in array]
#        for array in data.numpy()
#    ]
#    return json.dumps({'key': key, 'input_1': data})
