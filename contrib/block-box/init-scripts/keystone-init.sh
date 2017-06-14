#!/bin/bash
INIT_DB=${INIT_DB:-true}

if [ "$INIT_DB" = "true" ]; then
/bin/sh -c "keystone-manage db_sync"
fi
keystone-manage fernet_setup --keystone-user keystone --keystone-group keystone
keystone-manage credential_setup --keystone-user keystone --keystone-group keystone
keystone-manage bootstrap --bootstrap-password password \
  --bootstrap-admin-url http://localhost:35357/v3/ \
  --bootstrap-internal-url http://localhost:5000/v3/ \
  --bootstrap-public-url http://localhost:5000/v3/ \
  --bootstrap-region-id RegionOne
echo "ServerName localhost" >> /etc/apache2/apache2.conf
service apache2 restart
tail -f /var/log/apache2/error.log
