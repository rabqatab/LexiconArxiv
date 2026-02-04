# GROBID arm64 Dockerfile 검토 및 수정 제안 (Claude Code 전달용)

이 문서는 **arm64(AArch64) 환경에서 GROBID를 Docker로 정상 구동**하기까지의 검토 결과를  
Claude Code(또는 다른 LLM/협업자)에게 전달하기 위한 **정리된 기술 메모**다.

---

## 개요

- 대상: GROBID 0.8.0 + Docker + arm64
- 상태: **서비스 기동 성공**, PDF 처리 안정화 단계
- 목적: 현재 Dockerfile이 “올바른지” 검토하고, **잠재적 런타임 실패 지점**을 사전에 제거

---

## 전체 평가

현재 Dockerfile은 **방향이 올바르며**, arm64에서 가장 큰 두 장애물인

1. **Wapiti JNI 라이브러리**
2. **pdfalto(PDF → XML) 네이티브 바이너리**

를 직접 빌드해 주입하는 전략을 정확히 사용하고 있다.

다만, 그대로 둘 경우 **PDF 처리 시점에 다시 실패할 가능성이 높은 지점**이 있어
아래 수정 사항을 강하게 권장한다.

---

## ✅ 올바른 점 (이미 잘된 부분)

- Wapiti를 arm64에서 직접 빌드 후  
  `grobid-home/lib/lin-64/libwapiti.so` 에 배치  
  → GROBID 내부 로딩 경로와 정확히 일치
- Gradle 7 `installDist` 중복 파일 오류를  
  `duplicatesStrategy = EXCLUDE`로 해결
- 단일 fat-jar 대신 `installDist` 기반 distribution 실행  
  → 실제 운영에 더 안정적
- `grobid.yaml`을 최소 설정으로 덮어쓰지 않고 **기본 config 유지**

---

## ⚠️ 수정 강추 1: pdfalto 실행 파일 이름 문제

GROBID는 PDF 처리 시 보통 다음 경로를 호출한다:

```
grobid-home/pdfalto/lin-64/pdfalto_server
```

하지만 현재 Dockerfile에서는:

```
/opt/pdfalto/pdfalto → grobid-home/pdfalto/lin-64/pdfalto
```

만 복사하고 있음.

### 문제점
- pdfalto 빌드 결과에 `pdfalto_server`가 생성되는 경우
- GROBID가 이를 호출하면 **런타임에서 “파일 없음”으로 실패**

### 권장 수정
빌드 결과를 확인한 뒤, `pdfalto_server`가 존재하면 함께 복사:

```dockerfile
RUN ls -al /opt/pdfalto
RUN mkdir -p /opt/grobid/grobid-home/pdfalto/lin-64 \
 && cp /opt/pdfalto/pdfalto /opt/grobid/grobid-home/pdfalto/lin-64/pdfalto \
 && (test -f /opt/pdfalto/pdfalto_server && \
     cp /opt/pdfalto/pdfalto_server /opt/grobid/grobid-home/pdfalto/lin-64/pdfalto_server || true) \
 && chmod +x /opt/grobid/grobid-home/pdfalto/lin-64/pdfalto*
```

---

## ⚠️ 수정 강추 2: 런타임 이미지에 pdfalto 의존 라이브러리 누락

pdfalto는 **런타임에 다음 라이브러리들을 필요로 한다**:

- `libxml2`
- `libpng`

현재 runtime stage에는 `libstdc++6`만 설치되어 있음.

### 문제점
- 빌드는 성공해도, 실제 PDF 요청 시  
  **동적 라이브러리 로딩 실패로 처리 오류 발생 가능**

### 권장 수정 (runtime stage)

```dockerfile
RUN apt-get update && apt-get install -y \
    curl \
    libstdc++6 \
    libxml2 \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*
```

---

## ℹ️ 참고 사항

- `lin-64` 디렉터리 사용은 문제 없음  
  (GROBID 내부 코드 및 실제 이슈 로그에서도 해당 경로 사용)
- `linux-64` 대신 `lin-64`를 쓰는 것이 오히려 현실과 맞는 경우가 많음
- 포그라운드 실행 시 “모델 로딩에서 멈춘 것처럼 보이는 현상”은  
  **기동 완료 후 로그가 조용해지는 정상 동작**

---

## 결론 요약

- 현재 Dockerfile은 **90% 이상 올바른 상태**
- arm64에서 PDF 처리까지 안정적으로 하려면 아래 두 가지만 보완하면 됨:

1. `pdfalto_server` 실행 파일 대응
2. runtime 이미지에 `libxml2 / libpng` 추가

이 두 가지를 적용하면 **arm64 환경에서 GROBID를 실사용 수준으로 안정 운용 가능**하다.
