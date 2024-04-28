REPO=accuknox
IMGNAME=sastjob
IMGTAG=latest
IMG=${REPO}/${IMGNAME}:${IMGTAG}
build:
	docker buildx build -t ${IMG} .

push:
	docker push ${IMG}
