package pl.ksef.auth;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import org.yaml.snakeyaml.Yaml;
import pl.akmf.ksef.sdk.api.services.DefaultSignatureService;
import pl.akmf.ksef.sdk.client.model.auth.AuthenticationChallengeResponse;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

public class Main {

    // Usage:
    //   ./gradlew clean fatJar
    //   java -jar build/libs/ksef-auth.jar -c /opt/ksef/client/config/ksef-auth.yml
    //
    // Optional:
    //   -out file|stdout   (default: stdout)
    //   -dir /path/to/dir  (default: ./build/artifacts)
    //   -pollMs 500        (default: 500)
    //   -timeoutSec 120    (default: 120)
    public static void main(String[] args) throws Exception {
        Args a = Args.parse(args);

        Map<String, Object> cfg;
        try (InputStream in = Files.newInputStream(Path.of(a.configPath))) {
            cfg = new Yaml().load(in);
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> ksef = (Map<String, Object>) cfg.get("ksef");
        @SuppressWarnings("unchecked")
        Map<String, Object> api = (Map<String, Object>) ksef.get("api");
        @SuppressWarnings("unchecked")
        Map<String, Object> auth = (Map<String, Object>) ksef.get("auth");
        @SuppressWarnings("unchecked")
        Map<String, Object> sign = (Map<String, Object>) ksef.get("sign");

        String baseUrl = (String) api.get("baseUrl"); // e.g. https://ksef-test.mf.gov.pl/api/v2
        if (baseUrl.endsWith("/")) baseUrl = baseUrl.substring(0, baseUrl.length() - 1);

        String mfPublicKeyPath = (String) api.get("publicmfkey"); // path to MF public key (PEM)

        // IMPORTANT: tolerate extra fields from API (e.g. timestampMs)
        ObjectMapper om = JsonMapper.builder()
                .findAndAddModules()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build();

        // 1) mTLS HttpClient using AUTH keystore (cert: "Uwierzytelnienie")
        HttpClient http = buildMtlsClient(auth, ksef);

        // 2) POST /auth/challenge (send '{}' with Content-Type application/json)
        HttpRequest challengeReq = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + "/auth/challenge"))
                .header("Accept", "application/json")
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString("{}"))
                .build();

        HttpResponse<String> challengeResp = http.send(challengeReq, HttpResponse.BodyHandlers.ofString());
        if (challengeResp.statusCode() != 200) {
            fail("KSeF error on /auth/challenge (expected 200)", challengeResp);
        }

        AuthenticationChallengeResponse challenge =
                om.readValue(challengeResp.body(), AuthenticationChallengeResponse.class);

        // 3) Build AuthTokenRequest XML (authv2.xsd namespace)
        String nip = readNipFromConfigOrFail(ksef);
        String authTokenRequestXml = buildAuthTokenRequestXml(
                challenge.getChallenge(),
                nip,
                "certificateSubject"
        );

        // 4) XAdES sign AuthTokenRequest XML.
        // IMPORTANT: in your case auth certificate must be used for authentication flow.
        KeyMaterial authMat = readPkcs12(auth);
        DefaultSignatureService sig = new DefaultSignatureService();
        String signedXml = sig.sign(
                authTokenRequestXml.getBytes(StandardCharsets.UTF_8),
                authMat.cert,
                authMat.privateKey
        );

        // 5) POST /auth/xades-signature?verifyCertificateChain=false  (expected 202)
        HttpRequest xadesReq = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + "/auth/xades-signature?verifyCertificateChain=false"))
                .header("Accept", "application/json")
                .header("Content-Type", "application/xml")
                .POST(HttpRequest.BodyPublishers.ofString(signedXml, StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> initResp = http.send(xadesReq, HttpResponse.BodyHandlers.ofString());
        if (initResp.statusCode() != 202) {
            fail("KSeF error on /auth/xades-signature (expected 202)", initResp);
        }

        AuthenticationInitResponse init = om.readValue(initResp.body(), AuthenticationInitResponse.class);

        // 6) Poll GET /auth/{referenceNumber} until status.code != 100; success=200
        AuthenticationOperationStatusResponse status = pollAuthStatus(http, baseUrl, om, init, a);
        if (status.status == null || status.status.code != 200) {
            throw new IllegalStateException("Uwierzytelnianie NIE zakończyło się sukcesem. status="
                    + (status.status == null ? "null" : (status.status.code + " " + status.status.description)));
        }

        // 7) POST /auth/token/redeem -> accessToken + refreshToken (JWT)
        HttpRequest redeemReq = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + "/auth/token/redeem"))
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + init.authenticationToken.token)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();

        HttpResponse<String> redeemResp = http.send(redeemReq, HttpResponse.BodyHandlers.ofString());
        if (redeemResp.statusCode() != 200) {
            fail("KSeF error on /auth/token/redeem (expected 200)", redeemResp);
        }

        AuthenticationTokensResponse tokens =
                om.readValue(redeemResp.body(), AuthenticationTokensResponse.class);

        // 7b) Build runtime contract (AUTH DONE → runtime state)
        AuthRuntimeContext runtimeCtx = buildAuthRuntimeContext(baseUrl, mfPublicKeyPath, nip, tokens);

        // 8) Output + optional artifacts
        if ("file".equalsIgnoreCase(a.outMode)) {
            Path dir = Path.of(a.outDir);
            Files.createDirectories(dir);

            writeText(dir.resolve("01_challenge_response.json"), challengeResp.body());
            writeText(dir.resolve("02_auth_token_request.xml"), authTokenRequestXml);
            writeText(dir.resolve("03_auth_token_request_signed.xml"), signedXml);
            writeText(dir.resolve("04_auth_init_response.json"), initResp.body());
            writeText(dir.resolve("05_auth_status.json"), om.writerWithDefaultPrettyPrinter().writeValueAsString(status));
            writeText(dir.resolve("06_tokens.json"), om.writerWithDefaultPrettyPrinter().writeValueAsString(tokens));
            writeText(dir.resolve("07_auth_cert.pem"), pemFromCert(authMat.cert));

            // Runtime contract for SESSION/INVOICE consumers
            writeText(dir.resolve("08_auth_runtime_context.json"),
                    om.writerWithDefaultPrettyPrinter().writeValueAsString(runtimeCtx));

            System.out.println("OK. Artifacts saved to: " + dir.toAbsolutePath());
            System.out.println("referenceNumber: " + init.referenceNumber);
            System.out.println("accessToken.validUntil: " + tokens.accessToken.validUntil);
            System.out.println("refreshToken.validUntil: " + tokens.refreshToken.validUntil);
        } else if ("runtime".equalsIgnoreCase(a.outMode)) {
            // Strict runtime output (machine-readable contract)
            System.out.println(om.writerWithDefaultPrettyPrinter().writeValueAsString(runtimeCtx));
        } else {
            // Legacy human-readable output (kept for backward compatibility)
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("referenceNumber", init.referenceNumber);
            out.put("authenticationTokenValidUntil", init.authenticationToken.validUntil);
            out.put("accessToken", tokens.accessToken.token);
            out.put("accessTokenValidUntil", tokens.accessToken.validUntil);
            out.put("refreshToken", tokens.refreshToken.token);
            out.put("refreshTokenValidUntil", tokens.refreshToken.validUntil);
            System.out.println(om.writerWithDefaultPrettyPrinter().writeValueAsString(out));
        }

    }

    private static AuthenticationOperationStatusResponse pollAuthStatus(
            HttpClient http,
            String baseUrl,
            ObjectMapper om,
            AuthenticationInitResponse init,
            Args a
    ) throws Exception {
        long deadline = System.currentTimeMillis() + (a.pollTimeoutSeconds * 1000L);
        AuthenticationOperationStatusResponse status = null;

        while (System.currentTimeMillis() < deadline) {
            HttpRequest statusReq = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + "/auth/" + init.referenceNumber))
                    .header("Accept", "application/json")
                    .header("Authorization", "Bearer " + init.authenticationToken.token)
                    .GET()
                    .build();

            HttpResponse<String> statusResp = http.send(statusReq, HttpResponse.BodyHandlers.ofString());
            if (statusResp.statusCode() != 200) {
                fail("KSeF error on GET /auth/{referenceNumber} (expected 200)", statusResp);
            }

            status = om.readValue(statusResp.body(), AuthenticationOperationStatusResponse.class);

            if (status.status != null && status.status.code == 100) {
                Thread.sleep(a.pollIntervalMillis);
                continue;
            }
            break;
        }

        if (status == null) {
            throw new IllegalStateException("Auth status is null (unexpected).");
        }
        return status;
    }

    private static HttpClient buildMtlsClient(Map<String, Object> auth, Map<String, Object> ksef) throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> timeouts = (Map<String, Object>) ksef.get("timeouts");
        int connectSeconds = timeouts != null && timeouts.get("connectSeconds") != null ? (Integer) timeouts.get("connectSeconds") : 10;

        @SuppressWarnings("unchecked")
        Map<String, Object> authKs = (Map<String, Object>) auth.get("keystore");

        KeyStore ks = KeyStore.getInstance("PKCS12");
        try (InputStream in = Files.newInputStream(Path.of((String) authKs.get("path")))) {
            ks.load(in, ((String) authKs.get("password")).toCharArray());
        }

        KeyManagerFactory kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        kmf.init(ks, ((String) authKs.get("password")).toCharArray());

        SSLContext ssl = SSLContext.getInstance("TLS");
        ssl.init(kmf.getKeyManagers(), null, null);

        return HttpClient.newBuilder()
                .sslContext(ssl)
                .connectTimeout(Duration.ofSeconds(connectSeconds))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    private static KeyMaterial readPkcs12(Map<String, Object> section) throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> ksCfg = (Map<String, Object>) section.get("keystore");

        String path = (String) ksCfg.get("path");
        String password = (String) ksCfg.get("password");
        String alias = (String) ksCfg.get("alias");

        KeyStore ks = KeyStore.getInstance("PKCS12");
        try (InputStream in = Files.newInputStream(Path.of(path))) {
            ks.load(in, password.toCharArray());
        }

        X509Certificate cert = (X509Certificate) ks.getCertificate(alias);
        if (cert == null) throw new IllegalStateException("No certificate in keystore for alias: " + alias);

        PrivateKey pk = (PrivateKey) ks.getKey(alias, password.toCharArray());
        if (pk == null) throw new IllegalStateException("No private key in keystore for alias: " + alias);

        return new KeyMaterial(cert, pk);
    }

    private static String buildAuthTokenRequestXml(String challenge, String nip, String subjectIdentifierType) {
        // Minimal form aligned with authv2.xsd:
        // <AuthTokenRequest xmlns="http://ksef.mf.gov.pl/auth/token/2.0">
        //   <Challenge>...</Challenge>
        //   <ContextIdentifier><Nip>...</Nip></ContextIdentifier>
        //   <SubjectIdentifierType>certificateSubject</SubjectIdentifierType>
        // </AuthTokenRequest>
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                + "<AuthTokenRequest xmlns=\"http://ksef.mf.gov.pl/auth/token/2.0\">"
                + "<Challenge>" + escapeXml(challenge) + "</Challenge>"
                + "<ContextIdentifier><Nip>" + escapeXml(nip) + "</Nip></ContextIdentifier>"
                + "<SubjectIdentifierType>" + escapeXml(subjectIdentifierType) + "</SubjectIdentifierType>"
                + "</AuthTokenRequest>";
    }

    private static String escapeXml(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;").replace("'", "&apos;");
    }

    private static void writeText(Path path, String content) throws Exception {
        Files.writeString(path, content, StandardCharsets.UTF_8);
    }

    private static String pemFromCert(X509Certificate cert) throws Exception {
        String b64 = Base64.getMimeEncoder(64, "\n".getBytes(StandardCharsets.UTF_8))
                .encodeToString(cert.getEncoded());
        return "-----BEGIN CERTIFICATE-----\n" + b64 + "\n-----END CERTIFICATE-----\n";
    }

    private static void fail(String msg, HttpResponse<String> resp) {
        String body = resp.body() == null ? "" : resp.body();
        throw new IllegalStateException(msg + " HTTP " + resp.statusCode() + " body=" + body);
    }

    private static String readNipFromConfigOrFail(Map<String, Object> ksef) {
        @SuppressWarnings("unchecked")
        Map<String, Object> ctx = (Map<String, Object>) ksef.get("context");
        if (ctx != null && ctx.get("nip") != null) {
            return String.valueOf(ctx.get("nip"));
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> ctxId = (Map<String, Object>) ksef.get("contextIdentifier");
        if (ctxId != null && ctxId.get("value") != null) {
            return String.valueOf(ctxId.get("value"));
        }

        throw new IllegalStateException("Missing NIP in config. Add either ksef.context.nip or ksef.contextIdentifier.value");
    }

    // ===== Runtime contract =====

    /**
     * AuthRuntimeContext
     *
     * Minimalny kontrakt runtime po zakończonym AUTH, potrzebny do dalszych etapów:
     *  - SESSION (otwarcie sesji online)
     *  - INVOICE (wysyłka faktury)
     *  - CLOSE / UPO
     *
     * Nie zawiera artefaktów procesu AUTH (challenge, authenticationToken, referenceNumber, XAdES, certyfikaty podatnika).
     */
    public static class AuthRuntimeContext {
        public Runtime runtime;
        public Context context;
        public Tokens tokens;

        public static class Runtime {
            public String baseUrl;
            public String integrationMode;   // "TEST" | "PROD"
            public String mfPublicKeyPath;   // path to MF public key PEM
        }

        public static class Context {
            public String nip;               // resolved context (e.g. NIP)
        }

        public static class Tokens {
            public String accessToken;
            public String accessTokenValidUntil;      // ISO-8601 from API
            public String refreshToken;
            public String refreshTokenValidUntil;     // ISO-8601 from API
        }
    }


    private static AuthRuntimeContext buildAuthRuntimeContext(
            String baseUrl,
            String mfPublicKeyPath,
            String nip,
            AuthenticationTokensResponse tokens
    ) {
        AuthRuntimeContext ctx = new AuthRuntimeContext();

        AuthRuntimeContext.Runtime rt = new AuthRuntimeContext.Runtime();
        rt.baseUrl = baseUrl;
        rt.mfPublicKeyPath = mfPublicKeyPath;

        // Minimalna determinacja trybu (konserwatywnie): jeśli URL wskazuje środowisko testowe -> TEST, inaczej PROD.
        // Jeżeli dodasz kiedyś jawne pole w config, to ono powinno mieć pierwszeństwo.
        String u = baseUrl == null ? "" : baseUrl.toLowerCase();
        rt.integrationMode = (u.contains("ksef-test") || u.contains("test")) ? "TEST" : "PROD";

        AuthRuntimeContext.Context c = new AuthRuntimeContext.Context();
        c.nip = nip;

        AuthRuntimeContext.Tokens t = new AuthRuntimeContext.Tokens();
        t.accessToken = tokens != null && tokens.accessToken != null ? tokens.accessToken.token : null;
        t.accessTokenValidUntil = tokens != null && tokens.accessToken != null ? tokens.accessToken.validUntil : null;
        t.refreshToken = tokens != null && tokens.refreshToken != null ? tokens.refreshToken.token : null;
        t.refreshTokenValidUntil = tokens != null && tokens.refreshToken != null ? tokens.refreshToken.validUntil : null;

        ctx.runtime = rt;
        ctx.context = c;
        ctx.tokens = t;

        return ctx;
    }

    // ===== DTOs (minimal) =====

    public static class AuthenticationInitResponse {
        public String referenceNumber;
        public TokenInfo authenticationToken;
    }

    public static class AuthenticationOperationStatusResponse {
        public String startDate;
        public String authenticationMethod;
        public StatusInfo status;
        public Boolean isTokenRedeemed;
        public String lastTokenRefreshDate;
        public String refreshTokenValidUntil;
    }

    public static class StatusInfo {
        public int code;
        public String description;
        public Object details;
    }

    public static class AuthenticationTokensResponse {
        public TokenInfo accessToken;
        public TokenInfo refreshToken;
    }

    public static class TokenInfo {
        public String token;
        public String validUntil;
    }

    private static class KeyMaterial {
        final X509Certificate cert;
        final PrivateKey privateKey;
        KeyMaterial(X509Certificate cert, PrivateKey privateKey) {
            this.cert = cert;
            this.privateKey = privateKey;
        }
    }

    private static class Args {
        final String configPath;
        final String outMode;
        final String outDir;
        final int pollIntervalMillis;
        final int pollTimeoutSeconds;

        private Args(String configPath, String outMode, String outDir, int pollIntervalMillis, int pollTimeoutSeconds) {
            this.configPath = configPath;
            this.outMode = outMode;
            this.outDir = outDir;
            this.pollIntervalMillis = pollIntervalMillis;
            this.pollTimeoutSeconds = pollTimeoutSeconds;
        }

        static Args parse(String[] args) {
            if (args.length < 2 || !"-c".equals(args[0])) {
                System.err.println("Usage: java -jar ksef-auth.jar -c <config.yml> [-out file|runtime|stdout] [-dir <path>] [-pollMs 500] [-timeoutSec 120]");
                System.exit(1);
            }
            String cfg = args[1];
            String out = "stdout";
            String dir = "./build/artifacts";
            int pollMs = 500;
            int timeout = 120;

            for (int i = 2; i < args.length; i++) {
                switch (args[i]) {
                    case "-out":
                        out = args[++i];
                        break;
                    case "-dir":
                        dir = args[++i];
                        break;
                    case "-pollMs":
                        pollMs = Integer.parseInt(args[++i]);
                        break;
                    case "-timeoutSec":
                        timeout = Integer.parseInt(args[++i]);
                        break;
                    default:
                        System.err.println("Unknown arg: " + args[i]);
                        System.exit(1);
                }
            }
            return new Args(cfg, out, dir, pollMs, timeout);
        }
    }
}

