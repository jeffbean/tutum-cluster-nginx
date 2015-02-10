FROM nginx

# Install pip and nginx
RUN apt-get update && \
    apt-get install -y --no-install-recommends python-pip ca-certificates && \
    apt-get clean && \
    pip install requests==2.2.1 && \
    pip install Jinja2==2.7.2 && \
    rm -rf /var/lib/apt/lists/*


# PORT to load balance and to expose (also update the EXPOSE directive below)
ENV PORT 80

# MODE of operation (http, tcp)
ENV MODE http

# algorithm for load balancing (roundrobin, source, leastconn, ...)
ENV BALANCE roundrobin

# Virtual host
ENV VIRTUAL_HOST **None**

# SSL certificate to use (optional)
ENV SSL_CERT **None**

# Add scripts
ADD nginx.conf /etc/nginx/nginx.conf
ADD nginx.py /nginx.py
ADD nginx.j2 /nginx.j2
ADD run.sh /run.sh
RUN chmod +x /*.sh

EXPOSE 80 443
CMD ["/run.sh"]