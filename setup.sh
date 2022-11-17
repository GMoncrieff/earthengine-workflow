
#create gcloud project and define vars
######################################

#variables
export BUCKET=gs://test-bucket-ee-deploy
export MODEL_BUCKET=gs://ee-model-fortest
export DATAFLOW_BUCKET=gs://ee-model-dataflow-test
export REGION=us-central1
export PROJECT_ID=test-ee-deploy

gcloud config set project ${PROJECT_ID}

#set default region
gcloud config set compute/region ${REGION}
gcloud config set run/region ${REGION}
gcloud config set workflows/location ${REGION}

#enable services
gcloud services enable cloudscheduler.googleapis.com cloudfunctions.googleapis.com earthengine.googleapis.com cloudbuild.googleapis.com dataflow.googleapis.com run.googleapis.com workflows.googleapis.com


#create service account
gcloud iam service-accounts create ee-test-deploy \
--description="testing_ee_deploy" \
--display-name="test_ee_deploy"

export SERVICE_ACCOUNT=ee-test-deploy@test-ee-deploy.iam.gserviceaccount.com 

#assign roles to service account
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/iam.serviceAccountUser

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/earthengine.writer

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/storage.objectAdmin

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:ee-test-deploy@test-ee-deploy.iam.gserviceaccount.com \
--role=roles/run.invoker

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/dataflow.admin

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/dataflow.worker

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/workflows.invoker

#create service account key
gcloud iam service-accounts keys create sa-private-key.json \
--iam-account=${SERVICE_ACCOUNT}

#enable earth neinge on service account
https://signup.earthengine.google.com/#!/service_accounts

#make bucket for donwloads and predictions
gsutil mb ${BUCKET}

#optionally set lifecycle
gsutil lifecycle set lifecycle.json ${BUCKET}

#make bucket for dataflow model
gsutil mb ${DATAFLOW_BUCKET}

#make bucket for tf model
gsutil mb ${MODEL_BUCKET}
#put model in this bucket
gsutil cp -r model ${MODEL_BUCKET}


#create empty image collection on ee for results
earthengine --service_account_file sa-private-key.json create collection projects/test-ee-deploy/assets/ee_test

#deploy function to download ee inputs to model
################################################

 cd ee_function

#deploy cloud function
gcloud functions deploy main \
--runtime python37 \
--trigger-http \
--allow-unauthenticated

#test
curl $(gcloud functions describe main --format='value(httpsTrigger.url)') \
-X POST \
-H "content-type: application/json" \
-d '{"input": "test-bucket-ee-deploy"}'

#get url and insert into workflow.yaml
gcloud functions describe main --format='value(httpsTrigger.url)'

#deploy dataflow
##################

#build flex template
export TEMPLATE_IMAGE="gcr.io/${PROJECT_ID}/samples/dataflow/eetest-beam-run:latest"
export TEMPLATE_PATH="${DATAFLOW_BUCKET}/samples/dataflow/templates/eetest-beam-run.json"

#build docker image for template
gcloud builds submit --tag "${TEMPLATE_IMAGE}" .

#deploy template
gcloud dataflow flex-template build ${TEMPLATE_PATH} \
  --image "${TEMPLATE_IMAGE}" \
  --sdk-language "PYTHON" \
  --metadata-file "metadata.json"

#test the Flex Template.
gcloud dataflow flex-template run "ee-testing-flow-`date +%Y%m%d-%H%M%S`" \
    --template-file-gcs-location "$TEMPLATE_PATH" \
    --parameters input="gs://test-bucket-ee-deploy/2022-11-04/download/*.tfrecord.gz" \
    --parameters output="gs://test-bucket-ee-deploy/2022-11-04/predict/" \
    --parameters model="gs://ee-model-fortest/ee_test_model" \
    --parameters max_num_workers=6 \
    --parameters worker_machine_type=e2-standard-4 \
    --region "us-central1"


#upload results to earth engine
###############################

cd .. && cd ee_upload
export SERVICE_NAME=ee-upload

#build container image
gcloud builds submit --tag gcr.io/${PROJECT_ID}/${SERVICE_NAME}

#deploy
gcloud run deploy ${SERVICE_NAME} \
--image gcr.io/${PROJECT_ID}/${SERVICE_NAME} \
--platform managed \
--allow-unauthenticated

#test
curl $(gcloud run services describe ${SERVICE_NAME} --format 'value(status.url)') \
-X POST \
-H "content-type: application/json" \
-d '{"input": "gs://test-bucket-ee-deploy/2022-11-04"}'

#workflow to stich it all together
################################

cd ..

export WORKFLOW="ee-sample"
export DESCRIPTION="Earth Engine sample workflow"
export SOURCE="eeworkflow.yaml"

#deploy workflow
gcloud workflows deploy "${WORKFLOW}" --location="${REGION}" --service-account="${SERVICE_ACCOUNT}" --source="${SOURCE}" --description="${DESCRIPTION}"

#test
gcloud workflows run "${WORKFLOW}" \
--call-log-level=log-all-calls

#setup shedule to execute workflow
gcloud scheduler jobs create http ee-workflow-shedule \
--location=${REGION} \
--schedule="0 0 1 1 *" \
--uri="https://workflowexecutions.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/workflows/${WORKFLOW}/executions" \
--time-zone="Africa/Johannesburg" \
--oauth-service-account-email="${SERVICE_ACCOUNT}"

#DONE