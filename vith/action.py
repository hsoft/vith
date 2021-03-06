import pylxd

from .provision import prepare_debian, provision_with_ansible, set_static_ip_on_debian
from .util import ContainerStatus, get_config, get_container, is_provisioned
from .network import get_ipv4_ip, get_default_gateway, find_free_ip, wait_for_ipv4_ip, EtcHosts

def _setup_ip(container):
    ip = get_ipv4_ip(container)
    if not ip:
        print("No IP yet, waiting 10 seconds...")
        ip = wait_for_ipv4_ip(container)
    if not ip:
        print("Still no IP! Forcing a static IP...")
        container.stop(wait=True)
        gateway = get_default_gateway()
        forced_ip = find_free_ip(gateway)
        set_static_ip_on_debian(container, forced_ip, gateway)
        container.start(wait=True)
        ip = wait_for_ipv4_ip(container)
    if not ip:
        print("STILL no IP! Container is up, but probably broken.")
        print("Maybe that restarting it will help? Not trying to provision.")
    return ip

def _setup_hostnames(container, hostnames, target_ip):
    etchosts = EtcHosts()
    for hostname in hostnames:
        print("Setting {} to point to {}. sudo needed.".format(hostname, target_ip))
        etchosts.ensure_binding_present(hostname, target_ip)
    if etchosts.changed:
        etchosts.save()

def up():
    config = get_config()
    container = get_container()
    if container.status_code == ContainerStatus.Running:
        print("Container is already running!")
        return

    print("Starting container...")
    container.start(wait=True)
    if container.status_code != ContainerStatus.Running:
        print("Something went wrong trying to start the container.")
        return

    ip = _setup_ip(container)
    if not ip:
        return

    print("Container is up! IP: %s" % ip)

    hostnames = config.get('hostnames', [])
    if hostnames:
        _setup_hostnames(container, hostnames, ip)

    if is_provisioned(container):
        print("Already provisioned, not provisioning.")
        return
    provision(barebone=True)

def _unsetup_hostnames(container, hostnames):
    etchosts = EtcHosts()
    for hostname in hostnames:
        print("Unsetting {}. sudo needed.".format(hostname))
        etchosts.ensure_binding_absent(hostname)
    if etchosts.changed:
        etchosts.save()

def halt():
    config = get_config()
    container = get_container()
    if container.status_code == ContainerStatus.Stopped:
        print("The container is already stopped.")
        return

    hostnames = config.get('hostnames', [])
    if hostnames:
        _unsetup_hostnames(container, hostnames)

    print("Stopping...")
    try:
        container.stop(timeout=30, force=False, wait=True)
    except pylxd.exceptions.LXDAPIException:
        print("Can't stop the container. Forcing...")
        container.stop(force=True, wait=True)

def provision(barebone=None):
    config = get_config()
    container = get_container()
    if container.status_code != ContainerStatus.Running:
        print("The container is not running.")
        return

    if barebone is None: # None == only if the container isn't provisioned.
        barebone = not is_provisioned(container)

    if barebone:
        print("Doing bare bone setup on the machine...")
        prepare_debian(container)

    print("Provisioning container...")
    for provisioning_item in config['provisioning']:
        print("Provisioning with {}".format(provisioning_item['type']))
        provision_with_ansible(container, provisioning_item)

    container.config['user.vith.provisioned'] = 'true'
    container.save(wait=True)

def destroy():
    container = get_container(create=False)
    if container is None:
        print("Container doesn't exist, nothing to destroy.")
        return

    halt()
    container = get_container()
    print("Destroying...")
    container.delete(wait=True)
    print("Destroyed!")


