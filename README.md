GlusterFS
=========

This role installs and configures [GlusterFS](http://www.gluster.org/).

Usage
-----

You can add this role as a dependency of another role, or directly in your playbook.
You also have to define the `glusterfs_cluster_name` variable in your inventory.

### Dependencies

In your role's meta, add a dependency to this role using the syntax described below.

```yaml
# my_role/meta/main.yml
dependencies:
  - role: aerisloud.glusterfs
    gluster_volumes:
        - brick1
        - brick2
```

### Playbook

If you didn't define this role as a dependency of another role, you have to add it to your playbook.

```yaml
- hosts: mesos
  gather_facts: true
  sudo: true
  roles:
    - role: aeriscloud.glusterfs
      gluster_volumes:
        - brick1
        - brick2
```

### Inventory

```
[glusterfs]
node1.glusterfs
node2.glusterfs
node3.glusterfs

[glusterfs:vars]
glusterfs_cluster_name=glusterfs
```

Variables
---------

* `gluster_volumes` is a list of the volumes you want to create.
* `glusterfs_cluster_name` must be set to the name of the group containing all the nodes of the GlusterFS cluster.

See also
--------

* [Gluster website](http://www.gluster.org/)

