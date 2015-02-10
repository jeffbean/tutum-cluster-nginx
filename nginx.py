#!/usr/bin/env python
import logging
import os
from pprint import pformat
import time
import string
import subprocess
import sys
import re
import socket

import jinja2
import requests


logger = logging.getLogger(__name__)

# Config ENV
PORT = os.getenv("PORT", "80")
MODE = os.getenv("MODE", "http")
MAXCONN = os.getenv("MAXCONN", "4096")

BALANCE = os.getenv("BALANCE", 'least-conn')

SSL = os.getenv("SSL", "")
# come make this install and run the type of proxy you want.
PROXY_NAME = os.getenv("PROXY_NAME", 'nginx')

SESSION_COOKIE = os.getenv("SESSION_COOKIE")
OPTION = os.getenv("OPTION", "redispatch, httplog, dontlognull, forwardfor").split(",")
TIMEOUT = os.getenv("TIMEOUT", "connect 5000, client 50000, server 50000").split(",")
VIRTUAL_HOST = os.getenv("VIRTUAL_HOST", None)
TUTUM_CONTAINER_API_URL = os.getenv("TUTUM_CONTAINER_API_URL", None)
POLLING_PERIOD = max(int(os.getenv("POLLING_PERIOD", 30)), 5)

TUTUM_AUTH = os.getenv("TUTUM_AUTH")
DEBUG = os.getenv("DEBUG", False)

# Const var
PROXY_CMD = ['/usr/sbin/nginx', '-c', '/etc/nginx/nginx.conf']
LINK_ENV_PATTERN = "_PORT_%s_TCP" % PORT
LINK_ADDR_SUFFIX = LINK_ENV_PATTERN + "_ADDR"
LINK_PORT_SUFFIX = LINK_ENV_PATTERN + "_PORT"
TUTUM_URL_SUFFIX = "_TUTUM_API_URL"
VIRTUAL_HOST_SUFFIX = "_ENV_VIRTUAL_HOST"

# Global Var
PROXY_CURRENT_SUBPROCESS = None

endpoint_match = re.compile(r"(?P<proto>tcp|udp):\/\/(?P<addr>[^:]*):(?P<port>.*)")


class NginxConfig(object):
    pass


class NginxProxy(object):
    def __init__(self):
        self.config_file = '/etc/nginx/sites-enabled/django-tutum.conf'
        self.template_config = "nginx.j2"

        self.pid = None
        self.virtual_hosts = {}

    def get_backend_routes(self, dict_var):
        # Return sth like: {'HELLO_WORLD_1': {'addr': '172.17.0.103', 'port': '80'},
        # 'HELLO_WORLD_2': {'addr': '172.17.0.95', 'port': '80'}}
        addr_port_dict = {}
        for name, value in dict_var.iteritems():
            position = string.find(name, LINK_ENV_PATTERN)
            if position != -1:
                container_name = name[:position]
                add_port = addr_port_dict.get(container_name, {'addr': "", 'port': ""})
                try:
                    add_port['addr'] = socket.gethostbyname(container_name.lower())
                except socket.gaierror:
                    add_port['addr'] = socket.gethostbyname(container_name.lower().replace("_", "-"))
                if name.endswith(LINK_PORT_SUFFIX):
                    add_port['port'] = value
                addr_port_dict[container_name] = add_port

        return addr_port_dict

    def create_configuration(self, backend_routes_dict):
        """

        :param backend_routes_dict:
        :type backend_routes_dict dict
        :return:
        """
        logger.debug("Updating config\n backend_routes: %s\n virtual_host: %s", backend_routes, self.virtual_hosts)

        template_loader = jinja2.FileSystemLoader(searchpath="/")
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template(self.template_config)

        logger.debug('Backend dict: {}'.format(pformat(backend_routes_dict)))
        context_dict = self.genorate_context(backend_routes_dict)
        output_text = template.render(context=context_dict)

        logger.debug(output_text)
        return output_text

    def genorate_context(self, backend_routes_dict):
        config_context = {}
        config_context["backend"] = {}
        if self.virtual_hosts:
            for service_name, domain_name in self.virtual_hosts.items():
                if DEBUG:
                    logger.info('Processing sn [{}] domain [{}]'.format(service_name, domain_name))
                service_name = service_name.upper()
                if domain_name not in config_context['backend']:
                    config_context['backend'][domain_name] = []
                for container_name, addr_port in backend_routes_dict.items():
                    address_info_string = '{addr}:{port}'.format(**addr_port)
                    if container_name == service_name and address_info_string not in config_context['backend'][
                        domain_name]:
                        if DEBUG:
                            logger.info('Appending cn: [{}] domain: [{}] addr: [{}]'.format(container_name, domain_name,
                                                                               address_info_string))
                        config_context['backend'][domain_name].append(address_info_string)
        else:
            for container_name, addr_port in backend_routes_dict.items():
                container_name = container_name.rsplit('_', 1)[0]
                if container_name not in config_context['backend']:
                    config_context['backend'][container_name] = []
                address_info_string = '{addr}:{port}'.format(**addr_port)
                if address_info_string not in config_context['backend'][container_name]:
                    if DEBUG:
                        logger.info('Appending cn: [{}] addr: [{}]'.format(container_name,
                                                                           address_info_string))
                    config_context['backend'][container_name].append(address_info_string)

        if DEBUG:
            logger.info('context dict: {}'.format(config_context))
        return config_context

    def save_config_file(self, cfg_text):
        directory = os.path.dirname(self.config_file)
        if not os.path.exists(directory):
            os.makedirs(directory)

        with open(self.config_file, 'w') as file_h:
            file_h.write(cfg_text)
        logger.info("Config file is updated")

    def reload_proxy(self):
        if self.pid:
            # Reload proxy
            logger.info("Reloading {} proxy".format(PROXY_NAME))
            process = subprocess.Popen(PROXY_CMD + ["-s", "reload"])
            self.pid.wait()
            self.pid = process
        else:
            # Launch proxy
            logger.info("Launching proxy")
            self.pid = subprocess.Popen(PROXY_CMD)


    def update_virtual_hosts_from_environment(self):
        if VIRTUAL_HOST:
            # virtual_host specified using environment variables
            for host in VIRTUAL_HOST.split(","):
                tmp = host.split("=", 2)
                if len(tmp) == 2:
                    self.virtual_hosts[tmp[0].strip()] = tmp[1].strip()
        else:
            # virtual_host specified in the linked containers
            for name, value in os.environ.iteritems():
                position = string.find(name, VIRTUAL_HOST_SUFFIX)
                if position != -1 and value != "**None**":
                    hostname = name[:position]
                    self.virtual_hosts[hostname] = value
        if DEBUG:
            logger.info('virtual host dict: {}'.format(pformat(self.virtual_hosts)))


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout)
    logging.getLogger(__name__).setLevel(logging.DEBUG if DEBUG else logging.INFO)
    nginx = NginxProxy()

    # Tell the user the mode of autoupdate we are using, if any
    if TUTUM_CONTAINER_API_URL:
        if TUTUM_AUTH:
            logger.info("Nginx proxy has access to Tutum API - will reload list of backends every %d seconds",
                        POLLING_PERIOD)
        else:
            logger.warning(
                "Nginx proxy doesn't have access to Tutum API and it's running in Tutum - you might want to give "
                "an API role to this service for automatic backend reconfiguration")
    else:
        logger.info("Nginx proxy is not running in Tutum")
    session = requests.Session()
    headers = {"Authorization": TUTUM_AUTH}

    # Main loop
    old_text = ""
    while True:
        try:
            if TUTUM_CONTAINER_API_URL and TUTUM_AUTH:
                # Running on Tutum with API access - fetch updated list of environment variables
                r = session.get(TUTUM_CONTAINER_API_URL, headers=headers)
                r.raise_for_status()
                container_details = r.json()

                backend_routes = {}
                for link in container_details.get("linked_to_container", []):
                    for port, endpoint in link.get("endpoints", {}).iteritems():
                        if port == u"{0:s}/tcp".format(PORT):
                            backend_routes[link["name"]] = endpoint_match.match(endpoint).groupdict()
            else:
                # No Tutum API access - configuring backends based on static environment variables
                backend_routes = nginx.get_backend_routes(os.environ)

            # {u'NGINX_BF17913F_2': {'proto': u'tcp', 'port': u'8001', 'addr': u'172.17.0.30'},
            # u'NGINX_BF17913F_1': {'proto': u'tcp', 'port': u'8001', 'addr': u'172.17.0.27'}}
            if DEBUG:
                logger.info('Backend routes dict: {}'.format(pformat(backend_routes)))

            # Update backend routes
            nginx.update_virtual_hosts_from_environment()
            config_output = nginx.create_configuration(backend_routes)

            if old_text != config_output:
                logger.debug(u"Proxy configuration has been changed:\n{0:s}".format(config_output))
                nginx.save_config_file(config_output)
                nginx.reload_proxy()
                old_text = config_output
            else:
                logger.debug('No changes detected, no update.')
        except Exception as e:
            logger.exception("Error: %s" % e)

        time.sleep(POLLING_PERIOD)