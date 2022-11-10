import tensorflow as tf

import argparse

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, SetupOptions

from apache_beam.ml.inference.base import KeyedModelHandler
from apache_beam.ml.inference.base import RunInference


from .utils import (
    FEATURES,
    KeyedReadFromTFRecord, MapWriteToTFRecord, LandCoverModel,
    file_path_key, transpose_per_key, parse_key,
    break_up_patch, add_ndvi, create_example
)

    
def run():
    
    parser = argparse.ArgumentParser()
    
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument('--setup_file', required=False, default='./setup.py')

    args, beam_args = parser.parse_known_args()
    
    options = PipelineOptions(beam_args, setup_file=args.setup_file)
    options.view_as(SetupOptions).save_main_session = True
    p = beam.Pipeline(options=options)

    model_handler = KeyedModelHandler(LandCoverModel(args.model))

    outputs = (
        p
        | 'Read Earth Engine Output' >> KeyedReadFromTFRecord(args.input)
        | 'Create Keys from Position Information' >> beam.Map(lambda x: (f'{file_path_key(x[0])},{x[1]}', x[2]))
        | 'Parse Features' >> beam.MapTuple(lambda key, record: (key, tf.io.parse_single_example(record, FEATURES)))
        | 'Tranpose' >> beam.MapTuple(transpose_per_key)
        | 'add ndvi' >> beam.MapTuple(add_ndvi)
        | 'Break into tensor with pixels as rows' >> beam.FlatMap(break_up_patch)
        | 'Transform Data Dict into Tuples' \
            >> beam.MapTuple(lambda data_key, data_dict: (data_key, tf.transpose(list(data_dict.values()))))
        | 'add dim 1' \
            >> beam.MapTuple(lambda data_key, data_dict: (data_key, tf.expand_dims(data_dict, axis=1)))
        | "RunInference" >> RunInference(model_handler)
        | 'Parse Key' >> beam.MapTuple(parse_key)
        #| 'Extract Patch Key' >> beam.MapTuple(lambda k,v: (k[:2],v))
        | 'Create Tensor Flow Examples' >> beam.MapTuple(create_example)
        | 'Extract file key for grouping' >> beam.MapTuple(lambda k,v: (k[0],(k[1],v)))
        | 'Group by File Key' >> beam.GroupByKey()
        | 'Map-Write to TFRecord' >> beam.ParDo(MapWriteToTFRecord(), args.output)
    )
    
    p.run()
    