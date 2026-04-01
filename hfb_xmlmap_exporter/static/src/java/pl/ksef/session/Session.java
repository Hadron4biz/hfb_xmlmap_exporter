package pl.ksef.session;

import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;
import java.security.spec.MGF1ParameterSpec;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;

import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.crypto.Cipher;

public class Session {

    public static void main(String[] args) throws Exception {
        Path runtimeFile = parseArgs(args);

        AuthRuntimeContext ctx = loadAuthRuntimeContext(runtimeFile);
        validateRuntimeContext(ctx);

        // === ETAP 6: kryptografia sesji ===
        PublicKey mfPublicKey = loadMfPublicKey(Path.of(ctx.runtime.mfPublicKeyPath));

        byte[] aesKey = new byte[32]; // AES-256
        byte[] iv = new byte[16];     // 128-bit IV
        SecureRandom sr = new SecureRandom();
        sr.nextBytes(aesKey);
        sr.nextBytes(iv);

		byte[] encryptedSymmetricKey;
        try {
			Cipher cipher = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
			OAEPParameterSpec spec = new OAEPParameterSpec(
				"SHA-256",
				"MGF1",
				MGF1ParameterSpec.SHA256,
				PSource.PSpecified.DEFAULT
			);
			cipher.init(Cipher.ENCRYPT_MODE, mfPublicKey, spec);
			encryptedSymmetricKey = cipher.doFinal(aesKey);

            System.err.println("INFO: Używam algorytmu RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
        } catch (Exception e) {
            System.err.println("BŁĄD przy szyfrowaniu : " + e.getMessage());
            throw e;
        }

		String b64EncryptedKey = Base64.getEncoder().encodeToString(encryptedSymmetricKey);
		String b64Iv = Base64.getEncoder().encodeToString(iv);
		String b64AesKey = Base64.getEncoder().encodeToString(aesKey);

		// === TESTOWANIE BASE64 ===
		System.err.println("\n=== ENCRYPTION DATA FOR SESSION ===");
		System.err.println("AES Key (b64): " + b64AesKey);
		System.err.println("IV (b64): " + b64Iv);
		System.err.println("Encrypted Key (b64): " + b64EncryptedKey);
		
		// Zapisz te dane do pliku dla późniejszego użycia
		saveEncryptionDataToFile(b64AesKey, b64Iv, "encryption_data.txt");

		// === ETAP 7: POST /sessions/online ===
		String url = normalizeBaseUrl(ctx.runtime.baseUrl) + "/sessions/online";

        Map<String, Object> payload = new LinkedHashMap<>();
        Map<String, Object> formCode = new LinkedHashMap<>();
        formCode.put("systemCode", "FA (3)");
        formCode.put("schemaVersion", "1-0E");
        formCode.put("value", "FA");

        payload.put("formCode", formCode);

        Map<String, Object> encryptionPayload = new LinkedHashMap<>();
        encryptionPayload.put("encryptedSymmetricKey", b64EncryptedKey);
        encryptionPayload.put("initializationVector", b64Iv);
        
        payload.put("encryption", encryptionPayload);

        ObjectMapper om = new ObjectMapper();
        String jsonBody = om.writeValueAsString(payload);

        // DEBUG: pokaż co wysyłamy
        System.err.println("\n=== DEBUG: Payload to send ===");
        System.err.println(jsonBody);

        HttpClient http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();

        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + ctx.tokens.accessToken)
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody, StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

        System.err.println("\n=== API Response ===");
        System.err.println("HTTP Status: " + resp.statusCode());
        System.err.println("Response body: " + resp.body());

        if (resp.statusCode() != 201) {
            System.err.println("OPEN SESSION FAILED");
            System.err.println("HTTP " + resp.statusCode());
            System.err.println("Response body: " + resp.body());
            throw new IllegalStateException("Open session failed: HTTP " + resp.statusCode());
        }

        OpenOnlineSessionResponse sessionResp = om.readValue(resp.body(), OpenOnlineSessionResponse.class);

        // WAŻNE: Sprawdź status sesji po otwarciu
        checkSessionStatus(ctx.runtime.baseUrl, sessionResp.referenceNumber, ctx.tokens.accessToken);

        // Build output JSON z POPRAWIONĄ strukturą
        System.err.println("\n=== SAVING SESSION RUNTIME CONTEXT ===");
        System.err.println("Upewnij się że w /tmp/session_runtime.json są TE SAME dane szyfrowania!");
        
        // Tworzymy output z WŁAŚCIWĄ strukturą dla Invoice.java
        OutputSessionRuntimeContext sessionCtx = new OutputSessionRuntimeContext();
        sessionCtx.runtime = new OutputSessionRuntimeContext.Runtime();
        sessionCtx.runtime.baseUrl = ctx.runtime.baseUrl;
        sessionCtx.runtime.integrationMode = ctx.runtime.integrationMode;
        sessionCtx.runtime.mfPublicKeyPath = ctx.runtime.mfPublicKeyPath;
        
        sessionCtx.context = new OutputSessionRuntimeContext.Context();
        sessionCtx.context.nip = ctx.context.nip;
        
        sessionCtx.session = new OutputSessionRuntimeContext.SessionData();
        sessionCtx.session.referenceNumber = sessionResp.referenceNumber;
        sessionCtx.session.validUntil = sessionResp.validUntil;
        
        // KLUCZOWA ZMIANA: Używamy encryptionDebug z AES Key i IV
        sessionCtx.encryptionDebug = new OutputSessionRuntimeContext.EncryptionDebug();
        sessionCtx.encryptionDebug.aesKeyBase64 = b64AesKey;  // To samo co wysłane!
        sessionCtx.encryptionDebug.ivBase64 = b64Iv;          // To samo co wysłane!
        
        sessionCtx.tokens = new OutputSessionRuntimeContext.Tokens();
        sessionCtx.tokens.accessToken = ctx.tokens.accessToken;
        sessionCtx.tokens.accessTokenValidUntil = ctx.tokens.accessTokenValidUntil;
        sessionCtx.tokens.refreshToken = ctx.tokens.refreshToken;
        sessionCtx.tokens.refreshTokenValidUntil = ctx.tokens.refreshTokenValidUntil;

        // Zapisz do pliku (to będzie /tmp/session_runtime.json)
        Path outputFile = Path.of("/tmp/session_runtime.json");
        String sessionJson = om.writerWithDefaultPrettyPrinter().writeValueAsString(sessionCtx);
        Files.writeString(outputFile, sessionJson, StandardCharsets.UTF_8);
        
        System.err.println("Session runtime context saved to: " + outputFile);
        System.err.println("AES Key in output: " + b64AesKey);
        System.err.println("IV in output: " + b64Iv);

        // Also print to stdout for compatibility
        System.out.println(sessionJson);
    }
    
    private static void saveEncryptionDataToFile(String aesKeyB64, String ivB64, String filename) throws Exception {
        String content = "AES Key: " + aesKeyB64 + "\n" +
                        "IV: " + ivB64 + "\n";
        Files.writeString(Path.of(filename), content, StandardCharsets.UTF_8);
        System.err.println("Encryption data saved to: " + filename);
    }
    
    private static void checkSessionStatus(String baseUrl, String sessionReferenceNumber, String accessToken) throws Exception {
        String url = normalizeBaseUrl(baseUrl) + "/sessions/" + sessionReferenceNumber;
        
        HttpClient http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + accessToken)
                .GET()
                .build();
        
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        
        System.err.println("\n=== SESSION STATUS CHECK ===");
        System.err.println("HTTP Status: " + resp.statusCode());
        
        if (resp.statusCode() == 200) {
            ObjectMapper om = new ObjectMapper();
            Map<String, Object> statusResponse = om.readValue(resp.body(), Map.class);
            
            if (statusResponse.containsKey("status")) {
                Map<String, Object> status = (Map<String, Object>) statusResponse.get("status");
                Object code = status.get("code");
                
                if (code != null && code instanceof Number) {
                    int statusCode = ((Number) code).intValue();
                    
                    if (statusCode == 100) {
                        System.err.println("✓ Sesja otwarta (100) - gotowa do przyjmowania faktur");
                        return;
                    } else if (statusCode == 415) {
                        System.err.println("✗ BŁĄD: Sesja ma status 415 - problem z szyfrowaniem!");
                        System.err.println("   Przyczyna: KSeF nie może odszyfrować klucza AES");
                        System.err.println("   Rozwiązanie: Sprawdź czy używasz poprawnego certyfikatu MF");
                    } else {
                        System.err.println("? Nieznany status: " + statusCode);
                    }
                }
            }
            System.err.println("Full response: " + resp.body());
        } else {
            System.err.println("Nie udało się sprawdzić statusu: HTTP " + resp.statusCode());
        }
    }

    // ------------------------------------------------------------
    // Args / IO
    // ------------------------------------------------------------

    static Path parseArgs(String[] args) {
        if (args.length < 2 || !"--runtime-file".equals(args[0])) {
            throw new IllegalArgumentException("Usage: --runtime-file <auth_runtime_context.json>");
        }
        return Path.of(args[1]);
    }

    static AuthRuntimeContext loadAuthRuntimeContext(Path file) throws Exception {
        if (!Files.exists(file)) {
            throw new IllegalArgumentException("runtime file not found: " + file);
        }
        ObjectMapper om = new ObjectMapper()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        try (InputStream in = Files.newInputStream(file)) {
            return om.readValue(in, AuthRuntimeContext.class);
        }
    }

    static void validateRuntimeContext(AuthRuntimeContext ctx) {
        if (ctx == null) throw new IllegalStateException("AuthRuntimeContext is null");
        if (ctx.runtime == null) throw new IllegalStateException("runtime is null");
        if (isBlank(ctx.runtime.baseUrl)) throw new IllegalStateException("runtime.baseUrl is blank");
        if (isBlank(ctx.runtime.integrationMode)) throw new IllegalStateException("runtime.integrationMode is blank");
        if (isBlank(ctx.runtime.mfPublicKeyPath)) throw new IllegalStateException("runtime.mfPublicKeyPath is blank");
        if (!Files.exists(Path.of(ctx.runtime.mfPublicKeyPath))) {
            throw new IllegalStateException("MF public key file not found: " + ctx.runtime.mfPublicKeyPath);
        }

        if (ctx.tokens == null) throw new IllegalStateException("tokens is null");
        if (isBlank(ctx.tokens.accessToken)) throw new IllegalStateException("tokens.accessToken is blank");

        OffsetDateTime now = OffsetDateTime.now();
        OffsetDateTime accessUntil = parseOffsetDateTime(ctx.tokens.accessTokenValidUntil, "tokens.accessTokenValidUntil");
        if (now.isAfter(accessUntil)) {
            throw new IllegalStateException("accessToken expired: " + ctx.tokens.accessTokenValidUntil);
        }
    }

    static OffsetDateTime parseOffsetDateTime(String s, String fieldName) {
        if (isBlank(s)) throw new IllegalStateException(fieldName + " is blank");
        try {
            return OffsetDateTime.parse(s);
        } catch (DateTimeParseException e) {
            throw new IllegalStateException("Invalid datetime in " + fieldName + ": " + s, e);
        }
    }

    static boolean isBlank(String s) {
        return s == null || s.trim().isEmpty();
    }

    static String normalizeBaseUrl(String baseUrl) {
        if (baseUrl.endsWith("/")) return baseUrl.substring(0, baseUrl.length() - 1);
        return baseUrl;
    }

    // ------------------------------------------------------------
    // Crypto
    // ------------------------------------------------------------

    static PublicKey loadMfPublicKey(Path pemOrCertPath) throws Exception {
        try (InputStream in = Files.newInputStream(pemOrCertPath)) {
            CertificateFactory cf = CertificateFactory.getInstance("X.509");
            X509Certificate cert = (X509Certificate) cf.generateCertificate(in);
            return cert.getPublicKey();
        }
    }

    // ------------------------------------------------------------
    // DTOs dla AuthRuntimeContext (wejściowy)
    // ------------------------------------------------------------

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AuthRuntimeContext {
        public Runtime runtime;
        public Context context;
        public Tokens tokens;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Runtime {
        public String baseUrl;
        public String integrationMode;
        public String mfPublicKeyPath;

        public Integer schemaVersion;

        public int schemaVersionOrDefault(int def) {
            return (schemaVersion == null) ? def : schemaVersion;
        }
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Context {
        public String nip;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Tokens {
        public String accessToken;
        public String accessTokenValidUntil;
        public String refreshToken;
        public String refreshTokenValidUntil;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class OpenOnlineSessionResponse {
        public String referenceNumber;
        public String validUntil;
    }
    
    // ------------------------------------------------------------
    // DTOs dla OutputSessionRuntimeContext (wyjściowy - dla Invoice.java)
    // ZMIENIONA NAZWA: OutputSessionRuntimeContext zamiast SessionRuntimeContext
    // ------------------------------------------------------------
    
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class OutputSessionRuntimeContext {
        public Runtime runtime;
        public Context context;
        public SessionData session;
        public EncryptionDebug encryptionDebug;
        public Tokens tokens;
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Runtime {
            public String baseUrl;
            public String integrationMode;
            public String mfPublicKeyPath;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Context {
            public String nip;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class SessionData {
            public String referenceNumber;
            public String validUntil;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class EncryptionDebug {
            public String aesKeyBase64;
            public String ivBase64;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Tokens {
            public String accessToken;
            public String accessTokenValidUntil;
            public String refreshToken;
            public String refreshTokenValidUntil;
        }
    }
}
