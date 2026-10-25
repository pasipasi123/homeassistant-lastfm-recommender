ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 tzdata ca-certificates
COPY rootfs /
RUN chmod a+x /etc/services.d/lastfm_recommender/run /etc/services.d/lastfm_recommender/finish
LABEL org.opencontainers.image.title="Last.fm Recommender" \
    org.opencontainers.image.description="Rediscover forgotten Last.fm albums" \
    org.opencontainers.image.source="https://github.com/pasipasi123/homeassistant-lastfm-recommender" \
    org.opencontainers.image.licenses="Apache-2.0"
