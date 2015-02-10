#!/usr/bin/env python2
import json
import re
import jinja2

endpoint_match = re.compile(r"(?P<proto>tcp|udp):\/\/(?P<addr>[^:]*):(?P<port>.*)")

container_details = json.load(open('json_container_responce.json'))
backend_routes = {}
for link in container_details.get("linked_to_container", []):
    for port, endpoint in link.get("endpoints", {}).iteritems():
        if port == u"{0:s}/tcp".format("8001"):
            backend_routes[link["name"]] = endpoint_match.match(endpoint).groupdict()

print(backend_routes)
templateLoader = jinja2.FileSystemLoader(searchpath="../")
templateEnv = jinja2.Environment(loader=templateLoader)
template = templateEnv.get_template("nginx.j2")

context_dict = backend_routes
outputText = template.render(context=context_dict)

print(outputText)