package pl.ksef.session;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;

public class SessionClose {
    
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || !"--session-runtime".equals(args[0])) {
            throw new IllegalArgumentException("Usage: --session-runtime <session_runtime.json>");
        }
        
        Path sessionFile = Path.of(args[1]);
        String json = Files.readString(sessionFile);
        
        ObjectMapper om = new ObjectMapper();
        SessionRuntimeContext ctx = om.readValue(json, SessionRuntimeContext.class);
        
        // Zamknięcie sesji
        String url = normalizeBaseUrl(ctx.runtime.baseUrl) 
                   + "/sessions/online/" 
                   + ctx.session.referenceNumber 
                   + "/close";
        
        HttpClient http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + ctx.tokens.accessToken)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();
        
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        
        System.err.println("=== CLOSE SESSION RESPONSE ===");
        System.err.println("HTTP Status: " + resp.statusCode());
        System.err.println("Response: " + resp.body());

        int status = resp.statusCode();
        if (status != 202 && status != 204) {  // Zarówno 202 jak i 204 są OK!{
            throw new IllegalStateException("Failed to close session: " + resp.body());
        }
        
        System.out.println("{\"message\": \"Session closed successfully\", \"sessionReference\": \"" 
                          + ctx.session.referenceNumber + "\"}");
    }
    
    private static String normalizeBaseUrl(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
    
    // DTO klasy (te same co w Session.java)
    public static class SessionRuntimeContext {
        public Runtime runtime;
        public Context context;
        public SessionData session;
        public EncryptionDebug encryptionDebug;
        public Tokens tokens;
        
        public static class Runtime {
            public String baseUrl;
            public String integrationMode;
            public String mfPublicKeyPath;
        }
        
        public static class Context {
            public String nip;
        }
        
        public static class SessionData {
            public String referenceNumber;
            public String validUntil;
        }
        
        public static class EncryptionDebug {
            public String aesKeyBase64;
            public String ivBase64;
        }
        
        public static class Tokens {
            public String accessToken;
            public String accessTokenValidUntil;
            public String refreshToken;
            public String refreshTokenValidUntil;
        }
    }
}
