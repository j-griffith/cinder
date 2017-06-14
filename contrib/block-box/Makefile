CINDER_BRANCH ?= stable/ocata# master, stable/ocata, refs/changes/67/418167/1
PLATFORM ?= debian# ubuntu, centos

all: base lvm devbox
blockbox: base lvm

base:
	docker build https://git.openstack.org/openstack/loci-cinder.git\#:$(PLATFORM) --tag openstackloci/cinder:$(PLATFORM) --build-arg PROJECT_REF=${CINDER_BRANCH}

lvm:
	docker build https://git.openstack.org/openstack/loci-cinder.git\#:${PLATFORM}/lvm --tag openstackloci/cinder-lvm:$(PLATFORM) --build-arg PROJECT_REF=${CINDER_BRANCH}

devbox:
	cp ../../test-requirements.txt ./docker_files/
	docker build -t cinder-devenv -f ./docker_files/Dockerfile.cinder-devenv .
	rm ./docker_files/test-requirements.txt
