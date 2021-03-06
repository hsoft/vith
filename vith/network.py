import time
import re
import tempfile
import subprocess

from .util import get_client

def get_ipv4_ip(container):
    state = container.state()
    if state.network is None: # container is not running
        return ''
    eth0 = state.network['eth0']
    for addr in eth0['addresses']:
        if addr['family'] == 'inet':
            return addr['address']
    return ''

def wait_for_ipv4_ip(container, seconds=10):
    for i in range(seconds):
        time.sleep(1)
        ip = get_ipv4_ip(container)
        if ip:
            return ip
    return ''

def get_default_gateway():
    client = get_client()
    lxdbr0 = client.networks.get('lxdbr0')
    cidr = lxdbr0.config['ipv4.address']
    return cidr.split('/')[0]

def get_used_ips():
    client = get_client()
    result = []
    for c in client.containers.all():
        ip = get_ipv4_ip(c)
        if ip:
            result.append(ip)
    return result

def find_free_ip(gateway):
    prefix = '.'.join(gateway.split('.')[:-1])
    used_ips = set(get_used_ips())
    for i in range(1, 256):
        ip = '%s.%s' % (prefix, i)
        if ip != gateway and ip not in used_ips:
            return ip
    return None

RE_ETCHOST_LINE = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([\w\-_.]+)$')

class EtcHosts:
    def __init__(self, path='/etc/hosts'):
        self.path = path
        self.lines = open(self.path, 'rt', encoding='utf-8').readlines()
        self.changed = False
        self.vith_bindings = {}
        self.vith_section_begin = None
        self.vith_section_end = None
        for i, line in enumerate(self.lines):
            if self.vith_section_begin is None:
                if line.startswith('# BEGIN vith section'):
                    self.vith_section_begin = i
            elif self.vith_section_end is None:
                if line.startswith('# END vith section'):
                    self.vith_section_end = i
                else:
                    m = RE_ETCHOST_LINE.match(line.strip())
                    if m:
                        self.vith_bindings[m.group(2)] = m.group(1)
            else:
                break

    def ensure_binding_present(self, hostname, target_ip):
        if self.vith_bindings.get(hostname) != target_ip:
            self.vith_bindings[hostname] = target_ip
            self.changed = True

    def ensure_binding_absent(self, hostname):
        if hostname in self.vith_bindings:
            del self.vith_bindings[hostname]
            self.changed = True

    def save(self):
        tosave = self.lines[:]
        if self.vith_bindings:
            toinsert = ['# BEGIN vith section\n']
            toinsert += ['{} {}\n'.format(ip, host) for host, ip in self.vith_bindings.items()]
            toinsert.append('# END vith section\n')
        else:
            toinsert = []
        if self.vith_section_begin is not None:
            # Replace the current vith section with our new hosts
            begin = self.vith_section_begin
            end = self.vith_section_end + 1 if self.vith_section_end is not None else None
            tosave[begin:end] = toinsert
        else:
            # Append a new vith section at the end of the file
            tosave += toinsert
        with tempfile.NamedTemporaryFile('wt', encoding='utf-8') as fp:
            fp.writelines(tosave)
            fp.flush()
            cmd = "sudo cp {} {}".format(fp.name, self.path)
            p = subprocess.Popen(cmd, shell=True)
            p.wait()

