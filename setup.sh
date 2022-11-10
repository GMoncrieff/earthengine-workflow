
#create gcloud project
#####################

export BUCKET=gs://test-bucket-ee-deploy
export MODEL_BUCKET=gs://ee-model-fortest
export DATAFLOW_BUCKET=gs://ee-model-dataflow-test
export REGION=us-central1
export PROJECT_ID=test-ee-deploy

#gcloud projects create $PROJECT_ID
gcloud config set project $PROJECT_ID

#set default region ?
#gcloud config set compute/region us-central1
#gcloud config set run/region us-central1
#gcloud config set workflows/location ${REGION}

gcloud services enable cloudscheduler.googleapis.com cloudfunctions.googleapis.com earthengine.googleapis.com cloudbuild.googleapis.com dataflow.googleapis.com run.googleapis.com workflows.googleapis.com


#create service account
######################
gcloud iam service-accounts create ee-test-deploy \
--description="testing_ee_deploy" \
--display-name="test_ee_deploy"

export SERVICE_ACCOUNT=ee-test-deploy@test-ee-deploy.iam.gserviceaccount.com 


gcloud projects add-iam-policy-binding $PROJECT_ID \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/earthengine.writer

gcloud projects add-iam-policy-binding $PROJECT_ID \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/storage.objectAdmin

gcloud projects add-iam-policy-binding $PROJECT_ID \
--member=serviceAccount:ee-test-deploy@test-ee-deploy.iam.gserviceaccount.com \
--role=roles/run.invoker

gcloud projects add-iam-policy-binding $PROJECT_ID \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/dataflow.admin

gcloud projects add-iam-policy-binding $PROJECT_ID \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/dataflow.worker

gcloud projects add-iam-policy-binding $PROJECT_ID \
--member=serviceAccount:${SERVICE_ACCOUNT} \
--role=roles/workflows.invoker



#create key
gcloud iam service-accounts keys create sa-private-key.json \
--iam-account=${SERVICE_ACCOUNT}

#enable earth neinge on service account
https://signup.earthengine.google.com/#!/service_accounts



####BUCKETS
#############
#make bucket ofr donwloads and predictions
gsutil mb $BUCKET
#optioanlly set lifecycle
gsutil lifecycle set lifecycle.json $BUCKET_NAM

#make bucket for model
gsutil mb $DATAFLOW_BUCKET


#if needed
#make bucket for model
gsutil mb $MODEL_BUCKET
#put model in this bucket
gsutil cp -r model $MODEL_BUCKET


#create ic on ee
earthengine --service_account_file sa-private-key.json create collection projects/test-ee-deploy/assets/ee_test

################################
################################
 cd ee_function

#deploy cloud function
#########
gcloud functions deploy main \
--runtime python37 \
--trigger-http \
--allow-unauthenticated

#test
curl $(gcloud functions describe main --format='value(httpsTrigger.url)') \
-X POST \
-H "content-type: application/json" \
-d '{"input": "test-bucket-ee-deploy"}'

#get url
gcloud functions describe main --format='value(httpsTrigger.url)'
################################################
###################################



##copy model to folder
cd .. && cd ee_predict2
#move trained model to that bucket
gsutil -m cp -r $MODEL_BUCKET  ee_predict_beam

##################
#build flex template
export TEMPLATE_IMAGE="gcr.io/$PROJECT_ID/samples/dataflow/eetest-beam-run:latest"
export TEMPLATE_PATH="$DATAFLOW_BUCKET/samples/dataflow/templates/eetest-beam-run.json"

gcloud builds submit --tag "$TEMPLATE_IMAGE" .
gcloud dataflow flex-template build $TEMPLATE_PATH \
  --image "$TEMPLATE_IMAGE" \
  --sdk-language "PYTHON" \
  --metadata-file "metadata.json"


# Run the Flex Template.
gcloud dataflow flex-template run "ee-testing-flow-`date +%Y%m%d-%H%M%S`" \
    --template-file-gcs-location "$TEMPLATE_PATH" \
    --parameters input="gs://test-bucket-ee-deploy/2022-11-04/download2/*.tfrecord.gz" \
    --parameters output="gs://test-bucket-ee-deploy/2022-11-04/predict/" \
    --parameters model="gs://ee-model-fortest/ee_test_model" \
    --parameters max_num_workers=6 \
    --parameters worker_machine_type=e2-standard-4 \
    --region "us-central1"




#################
################
#upload

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

##########
#########
#workflow

cd ..


export WORKFLOW="ee-sample"
export DESCRIPTION="Earth Engine sample workflow"
export SOURCE="eeworkflowtest.yaml"

gcloud workflows deploy "${WORKFLOW}" --location="${REGION}" --service-account="${SERVICE_ACCOUNT}" --source="${SOURCE}" --description="${DESCRIPTION}"

gcloud scheduler jobs create http ee-workflow-shedule \
--location=${REGION} \
--schedule="0 0 1 1 *" \
--uri="https://workflowexecutions.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/workflows/${WORKFLOW}/executions" \
--time-zone="Africa/Johannesburg" \
--oauth-service-account-email="${SERVICE_ACCOUNT}"

