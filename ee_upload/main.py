import logging
import os
import json
from google.cloud import storage
import re
import subprocess

from flask import Flask, request, jsonify

app = Flask(__name__)


def act(input):
    # get mixer.json path
    bucket, prefix = input.split("//")[-1].split("/")
    storage_client = storage.Client()
    blobs = storage_client.list_blobs(bucket, prefix=prefix + "/download/")
    blobs = [blob.name for blob in blobs]
    regex = re.compile("^.*\.(json)$")
    mixer = [string for string in blobs if re.match(regex, string)][0]
    mixer_path = "gs://" + bucket + "/" + mixer
    # date is in mixer.json path
    date = mixer_path.rsplit("/")[-3]

    # path to predicitons
    tfrecords_pattern = input + "/predict/" + "*.tfrecord"

    # assign date to filename
    asset_id = "projects/test-ee-deploy/assets/ee_test/image_predict_" + prefix

    # earth engine upload command
    cmd = f"earthengine --service_account_file sa-private-key.json upload image --asset_id={asset_id} --time_start={date} {tfrecords_pattern} {mixer_path}"
    print(cmd)
    output = subprocess.run(cmd, capture_output=True, shell=True)

    # return cmd output
    return {
        "stdout": output.stdout.decode("utf-8"),
        "stderr": output.stderr.decode("utf-8"),
    }


@app.route("/", methods=["POST"])
def index():
    content = json.loads(request.data)
    input = content["input"]

    print(input)
    files = act(input)

    return jsonify(files), 200


if __name__ != "__main__":
    # Redirect Flask logs to Gunicorn logs
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    app.logger.info("Service started...")
else:
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
