# GROBID ARM64 Dockerfile
# Build: docker build --no-cache -t grobid-arm64 ./docker/grobid-arm64
# Run:   docker run -d --rm --name grobid -p 8070:8070 grobid-arm64

FROM eclipse-temurin:17-jdk AS builder

RUN apt-get update && apt-get install -y \
    git \
    build-essential cmake swig pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 --branch 0.8.0 https://github.com/kermitt2/grobid.git

# --- Build Wapiti (arm64) and install libwapiti.so into grobid-home ---
RUN git clone --depth 1 https://github.com/kermitt2/Wapiti.git /opt/wapiti
WORKDIR /opt/wapiti
RUN mkdir -p build && cd build && cmake .. && make -j"$(nproc)"

# Place arm64 libwapiti.so where GROBID expects it
WORKDIR /opt/grobid
RUN mkdir -p /opt/grobid/grobid-home/lib/lin-64 \
 && cp /opt/wapiti/build/libwapiti.so /opt/grobid/grobid-home/lib/lin-64/libwapiti.so

# Verify it's there
RUN ls -al /opt/grobid/grobid-home/lib/lin-64

# Fix Gradle 7 duplicate entries error in installDist
RUN printf '\n// Added by Docker build to avoid Gradle duplicate entries in installDist\n' >> grobid-service/build.gradle \
 && printf 'tasks.named("installDist") { duplicatesStrategy = DuplicatesStrategy.EXCLUDE }\n' >> grobid-service/build.gradle

# Build grobid-service distribution
RUN ./gradlew clean :grobid-service:installDist --no-daemon

FROM eclipse-temurin:17-jre

RUN apt-get update && apt-get install -y \
    curl \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/grobid

COPY --from=builder /opt/grobid/grobid-home ./grobid-home
COPY --from=builder /opt/grobid/grobid-service/build/install/grobid-service ./grobid-service

EXPOSE 8070
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
  CMD curl -f http://localhost:8070/api/isalive || exit 1

CMD ["./grobid-service/bin/grobid-service", "server", "grobid-home/config/grobid.yaml"]
