#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2014, Taneli Leppä <taneli@crasman.fi>
#
# This file is part of Ansible (sort of)
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.


DOCUMENTATION = """
module: gluster_volume
short_description: Manage GlusterFS volumes
description:
  - Create, remove, start, stop and tune GlusterFS volumes
version_added: "1.9"
options:
  name:
    required: true
    description:
      - The volume name
  state:
    required: true
    choices: [ 'present', 'absent', 'started', 'stopped' ]
    description:
      - Use present/absent ensure if a volume exists or not,
        use started/stopped to control it's availability.
  cluster:
    required: false
    description:
      - List of hosts to use for probing and brick setup
  host:
    required: false
    description:
      - Override local hostname (for peer probing purposes)
  replicas:
    required: false
    description:
      - Replica count for volume
  stripes:
    required: false
    description:
      - Stripe count for volume
  transport:
    required: false
    choices: [ 'tcp', 'rdma', 'tcp,rdma' ]
    description:
      - Transport type for volume
  brick:
    required: false
    description:
      - Brick path on servers
  start_on_create:
    choices: [ 'yes', 'no']
    required: false
    description:
      - Controls whether the volume is started after creation or not, defaults to yes
  rebalance:
    choices: [ 'yes', 'no']
    required: false
    description:
      - Controls whether the cluster is rebalanced after changes
  directory:
    required: false
    description:
      - Directory for limit-usage
  options:
    required: false
    description:
      - A dictionary/hash with options/settings for the volume
  quota:
    required: false
    description:
      - Quota value for limit-usage (be sure to use 10.0MB instead of 10MB, see quota list)
notes:
  - "Requires cli tools for GlusterFS on servers"
  - "Will add new bricks, but not remove them"
author: Taneli Leppä
"""

EXAMPLES = """
- name: create gluster volume
  gluster_volume: state=present name=test1 brick=/bricks/brick1/g1 rebalance=yes hosts:"{{ play_hosts }}"
  run_once: true

- name: tune
  gluster_volume: state=present name=test1 options='{performance.cache-size: 256MB}'

- name: start gluster volume
  gluster_volume: status=started name=test1

- name: limit usage
  gluster_volume: state=present name=test1 directory=/foo quota=20.0MB

- name: stop gluster volume
  gluster_volume: state=stopped name=test1

- name: remove gluster volume
  gluster_volume: state=absent name=test1
"""

import time
import socket

def main():


    def run_gluster(gargs, **kwargs):
        args = [glusterbin]
        args.extend(gargs)
        rc, out, err = module.run_command(args, **kwargs)
        if rc != 0:
            module.fail_json(msg='error running gluster (%s) command (rc=%d): %s' % (' '.join(args), rc, out if out != '' else err))
        return out

    def run_gluster_nofail(gargs, **kwargs):
        args = [glusterbin]
        args.extend(gargs)
        rc, out, err = module.run_command(args, **kwargs)
        if rc != 0:
            return None
        return out

    def run_gluster_yes(gargs):
        args = [glusterbin]
        args.extend(gargs)
        rc, out, err = module.run_command(args, data='y\n')
        if rc != 0:
            module.fail_json(msg='error running gluster (%s) command (rc=%d): %s' % (' '.join(args), rc, out if out != '' else err))
        return out

    def get_peers():
        out = run_gluster([ 'peer', 'status'])
        i = 0
        peers = {}
        hostname = None
        uuid = None
        state = None
        for row in out.split('\n'):
            if ': ' in row:
                key, value = row.split(': ')
                if key.lower() == 'hostname':
                    hostname = value
                if key.lower() == 'uuid':
                    uuid = value
                if key.lower() == 'state':
                    state = value
                    peers[hostname] = [ uuid, state ]
        return peers

    def get_volumes():
        out = run_gluster([ 'volume', 'info' ])

        volumes = {}
        volume = {}
        for row in out.split('\n'):
            if ': ' in row:
                key, value = row.split(': ')
                if key.lower() == 'volume name':
                    volume['name'] = value
                    volume['options'] = {}
                    volume['quota'] = False
                if key.lower() == 'volume id':
                    volume['id'] = value
                if key.lower() == 'status':
                    volume['status'] = value
                if key.lower() == 'transport-type':
                    volume['transport'] = value
                if key.lower() != 'bricks' and key.lower()[:5] == 'brick':
                    if not 'bricks' in volume:
                        volume['bricks'] = []
                    volume['bricks'].append(value)
                # Volume options
                if '.' in key:
                    if not 'options' in volume:
                        volume['options'] = {}
                    volume['options'][key] = value
                    if key == 'features.quota' and value == 'on':
                        volume['quota'] = True
            else:
                if row.lower() != 'bricks:' and row.lower() != 'options reconfigured:':
                    if len(volume) > 0:
                        volumes[volume['name']] = volume
                    volume = {}
        return volumes

    def get_quotas(name, nofail):
        quotas = {}
        if nofail:
            out = run_gluster_nofail([ 'volume', 'quota', name, 'list' ])
            if not out:
                return quotas
        else:
            out = run_gluster([ 'volume', 'quota', name, 'list' ])
        for row in out.split('\n'):
            if row[:1] == '/':
                q = re.split('\s+', row)
                quotas[q[0]] = q[1]
        return quotas

    def wait_for_peer(host):
        for x in range(0, 4):
            peers = get_peers()
            if host in peers and peers[host][1].lower().find('peer in cluster') != -1:
                return True
            time.sleep(1)
        return False

    def probe(host):
        run_gluster([ 'peer', 'probe', host ])
        if not wait_for_peer(host):
            module.fail_json(msg='failed to probe peer %s' % host)
        changed = True

    def probe_all_peers(hosts, peers, myhostname):
        for host in hosts:
            if host not in peers:
                # dont probe ourselves
                if myhostname != host:
                    probe(host)

    def create_volume(name, stripe, replica, transport, hosts, brick, force):
        args = [ 'volume', 'create' ]
        args.append(name)
        if stripe:
            args.append('stripe')
            args.append(str(stripe))
        if replica:
            args.append('replica')
            args.append(str(replica))
        args.append('transport')
        args.append(transport)
        for host in hosts:
            args.append(('%s:%s' % (host, brick)))
        if force:
            args.append('force')
        run_gluster(args)

    def start_volume(name):
        run_gluster([ 'volume', 'start', name ])

    def stop_volume(name):
        run_gluster_yes([ 'volume', 'stop', name ])

    def set_volume_option(name, option, parameter):
        run_gluster([ 'volume', 'set', name, option, parameter ])

    def add_brick(name, brick):
        run_gluster([ 'volume', 'add-brick', name, brick ])

    def do_rebalance(name):
        run_gluster(['volume', 'rebalance', name, 'start'])

    def enable_quota(name):
        run_gluster([ 'volume', 'quota', name, 'enable' ])

    def set_quota(name, directory, value):
            run_gluster([ 'volume', 'quota', name, 'limit-usage', directory, value ])


    ### MAIN ###

    module = AnsibleModule(
        argument_spec=dict(
            name=dict(required=True, default=None, aliases=['volume']),
            state=dict(required=True, choices=[ 'present', 'absent', 'started', 'stopped', 'rebalanced' ]),
            cluster=dict(required=False, default=None, type='list'),
            host=dict(required=False, default=None),
            stripes=dict(required=False, default=None, type='int'),
            replicas=dict(required=False, default=None, type='int'),
            transport=dict(required=False, default='tcp', choices=[ 'tcp', 'rdma', 'tcp,rdma' ]),
            brick=dict(required=False, default=None),
            start_on_create=dict(required=False, default=True, type='bool'),
            rebalance=dict(required=False, default=False, type='bool'),
            options=dict(required=False, default=None, type='dict'),
            quota=dict(required=False),
            directory=dict(required=False, default=None),
            force=dict(required=False, default=False, type='bool'),
            )
        )

    glusterbin = module.get_bin_path('gluster', True)

    changed = False

    action = module.params['state']
    volume_name = module.params['name']
    cluster= module.params['cluster']
    brick_path = module.params['brick']
    stripes = module.params['stripes']
    replicas = module.params['replicas']
    transport = module.params['transport']
    myhostname = module.params['host']
    start_on_create = module.boolean(module.params['start_on_create'])
    rebalance = module.boolean(module.params['rebalance'])
    force = module.boolean(module.params['force'])

    if not myhostname:
        myhostname = socket.gethostname()

    options = module.params['options']
    quota = module.params['quota']
    directory = module.params['directory']


    # get current state info
    peers = get_peers()
    volumes = get_volumes()
    quotas = {}
    if volume_name in volumes and volumes[volume_name]['quota'] and volumes[volume_name]['status'].lower() == 'started':
        quotas = get_quotas(volume_name, True)

    # do the work!
    if action == 'absent':
        if volume_name in volumes:
            run_gluster([ 'volume', 'delete', name ])
            changed = True

    if action == 'present':
        probe_all_peers(cluster, peers, myhostname)

        # create if it doesn't exist
        if volume_name not in volumes:
            create_volume(volume_name, stripes, replicas, transport, cluster, brick_path, force)
            changed = True

            # update volumes after the creation
            volumes = get_volumes()

        if volume_name in volumes:
            if volumes[volume_name]['status'].lower() != 'started' and start_on_create:
                start_volume(volume_name)
                changed = True

            # switch bricks
            new_bricks = []
            removed_bricks = []
            all_bricks = []
            for node in cluster:
                brick = '%s:%s' % (node, brick_path)
                all_bricks.append(brick)
                if brick not in volumes[volume_name]['bricks']:
                    new_bricks.append(brick)

            # this module does not yet remove bricks, but we check those anyways
            for brick in volumes[volume_name]['bricks']:
                if brick not in all_bricks:
                    removed_bricks.append(brick)

            for brick in new_bricks:
                add_brick(volume_name, brick)
                changed = True

            # handle quotas
            if quota:
                if not volumes[volume_name]['quota']:
                    enable_quota(volume_name)
                quotas = get_quotas(volume_name, False)
                if directory not in quotas or quotas[directory] != quota:
                    set_quota(volume_name, directory, quota)
                    changed = True

            # set options
            if options:
                for option in options.keys():
                    if option not in volumes[volume_name]['options'] or volumes[volume_name]['options'][option] != options[option]:
                        set_volume_option(volume_name, option, options[option])
                        changed = True

        else:
            module.fail_json(msg='failed to create volume %s' % volume_name)

    if volume_name not in volumes:
        module.fail_json(msg='volume not found %s' % volume_name)

    if action == 'started':
        if volumes[volume_name]['status'].lower() != 'started':
            start_volume(volume_name)
            changed = True

    if action == 'stopped':
        if volumes[volume_name]['status'].lower() != 'stopped':
            stop_volume(volume_name)
            changed = True

    if changed:
        volumes = get_volumes()
        if rebalance:
            do_rebalance(volume_name)

    facts = {}
    facts['glusterfs'] = { 'peers': peers, 'volumes': volumes, 'quotas': quotas }

    module.exit_json(changed=changed, ansible_facts=facts)

# import module snippets
from ansible.module_utils.basic import *
main()
