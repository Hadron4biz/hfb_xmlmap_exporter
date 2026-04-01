package pl.ksef.session;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class DownloadUPO {
    
    private static final ObjectMapper objectMapper = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false)
            .enable(SerializationFeature.INDENT_OUTPUT);
    
    private static final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .build();
    
    public static void main(String[] args) {
        Map<String, Object> result = new LinkedHashMap<>();
        
        try {
            // Validate arguments
            if (args.length < 2) {
                result.put("status", "ERROR");
                result.put("message", "Missing arguments. Usage: --session-runtime <file.json>");
                printUsage();
                System.out.println(objectMapper.writeValueAsString(result));
                System.exit(1);
            }
            
            if (!"--session-runtime".equals(args[0])) {
                result.put("status", "ERROR");
                result.put("message", "First argument must be --session-runtime");
                printUsage();
                System.out.println(objectMapper.writeValueAsString(result));
                System.exit(1);
            }
            
            Path sessionFile = Path.of(args[1]);
            System.err.println("Loading file: " + sessionFile.toAbsolutePath());
            
            // Check file before loading
            if (!Files.exists(sessionFile)) {
                throw new IllegalStateException("File does not exist: " + sessionFile);
            }
            
            String fileContent = Files.readString(sessionFile, StandardCharsets.UTF_8);
            if (fileContent.trim().isEmpty()) {
                throw new IllegalStateException("File is empty or contains only whitespace: " + sessionFile);
            }
            
            // Try to parse
            SessionRuntimeContext ctx = objectMapper.readValue(fileContent, SessionRuntimeContext.class);
            
            // Validate required fields
            if (ctx.runtime == null || ctx.runtime.baseUrl == null) {
                throw new IllegalStateException("Missing runtime.baseUrl in file");
            }
            if (ctx.session == null || ctx.session.referenceNumber == null) {
                throw new IllegalStateException("Missing session.referenceNumber in file");
            }
            if (ctx.tokens == null) {
                throw new IllegalStateException("Missing tokens section in file");
            }
            
            // Proceed with download
            result = downloadUPO(ctx);
            
        } catch (Exception e) {
            result.clear();
            result.put("status", "ERROR");
            result.put("message", e.getMessage());
            result.put("errorType", e.getClass().getSimpleName());
            
            // Add stack trace for debugging
            StringWriter sw = new StringWriter();
            e.printStackTrace(new PrintWriter(sw));
            result.put("stackTrace", sw.toString());
        }
        
        // Output result
        try {
            System.out.println(objectMapper.writeValueAsString(result));
        } catch (Exception e) {
            System.err.println("FATAL: Could not output JSON: " + e.getMessage());
            System.err.println("Result was: " + result.toString());
        }
    }
    
    private static Map<String, Object> downloadUPO(SessionRuntimeContext ctx) throws Exception {
        Map<String, Object> result = new LinkedHashMap<>();
        
        // 1. Validate and refresh token if needed
        System.err.println("=== TOKEN VALIDATION ===");
        if (!isTokenValid(ctx.tokens.accessTokenValidUntil)) {
            System.err.println("⚠️ Access token expired at: " + ctx.tokens.accessTokenValidUntil);
            
            if (ctx.tokens.refreshToken == null || ctx.tokens.refreshToken.isEmpty()) {
                throw new IllegalStateException("Access token expired and no refresh token available");
            }
            
            System.err.println("🔄 Refreshing token...");
            ctx = refreshTokens(ctx);
            System.err.println("✅ Token refreshed. New expiry: " + ctx.tokens.accessTokenValidUntil);
        } else {
            System.err.println("✅ Access token is valid until: " + ctx.tokens.accessTokenValidUntil);
        }
        
        // 2. Get session status to obtain UPO reference
        System.err.println("\n=== GETTING SESSION STATUS ===");
        String statusUrl = normalizeUrl(ctx.runtime.baseUrl) + "/sessions/" + ctx.session.referenceNumber;
        System.err.println("URL: " + statusUrl);
        
        HttpRequest statusReq = HttpRequest.newBuilder()
                .uri(URI.create(statusUrl))
                .header("Accept", "application/json")
                .header("Authorization", "Bearer " + ctx.tokens.accessToken)
                .GET()
                .build();
        
        HttpResponse<String> statusResp = httpClient.send(statusReq, HttpResponse.BodyHandlers.ofString());
        
        System.err.println("HTTP Status: " + statusResp.statusCode());
        
        if (statusResp.statusCode() == 401) {
            throw new IllegalStateException("Token invalid even after refresh. Full re-authentication required.");
        }
        
        if (statusResp.statusCode() != 200) {
            throw new IllegalStateException("Failed to get session status: HTTP " + statusResp.statusCode() + 
                                           "\nResponse: " + statusResp.body());
        }
        
        Map<String, Object> statusData = objectMapper.readValue(statusResp.body(), Map.class);
        result.put("sessionStatus", statusData);
        
        // 3. Check if UPO is available
        if (!statusData.containsKey("upo")) {
            result.put("status", "UPO_NOT_READY");
            result.put("message", "UPO not yet generated for this session");
            return result;
        }
        
        Map<String, Object> upoData = (Map<String, Object>) statusData.get("upo");
        List<Map<String, Object>> pages = (List<Map<String, Object>>) upoData.get("pages");
        
        if (pages == null || pages.isEmpty()) {
            result.put("status", "UPO_NO_PAGES");
            result.put("message", "UPO exists but has no pages");
            return result;
        }
        
        System.err.println("✅ UPO available. Pages: " + pages.size());
        
        // 4. Try to download UPO via API first
        Map<String, Object> firstPage = pages.get(0);
        String upoRef = (String) firstPage.get("referenceNumber");
        String directUrl = (String) firstPage.get("downloadUrl");
        
        System.err.println("\n=== DOWNLOADING UPO ===");
        System.err.println("UPO Reference: " + upoRef);
        
        byte[] upoContent = null;
        String downloadMethod = null;
        
        // Try API endpoint first
        try {
            System.err.println("Trying API endpoint...");
            upoContent = downloadViaAPI(ctx, upoRef);
            downloadMethod = "API";
            System.err.println("✅ Success via API");
        } catch (Exception apiError) {
            System.err.println("❌ API download failed: " + apiError.getMessage());
            
            // Fallback to direct URL if available
            if (directUrl != null && !directUrl.isEmpty()) {
                System.err.println("Trying direct URL...");
                try {
                    upoContent = downloadViaDirectURL(directUrl);
                    downloadMethod = "DIRECT_URL";
                    System.err.println("✅ Success via direct URL");
                } catch (Exception directError) {
                    System.err.println("❌ Direct URL also failed: " + directError.getMessage());
                    throw new IllegalStateException("Both API and direct URL failed: " + 
                            apiError.getMessage() + " / " + directError.getMessage());
                }
            } else {
                throw apiError;
            }
        }
        
        // 5. Save UPO to file and prepare result
        String fileName = "UPO_" + ctx.session.referenceNumber + ".xml";
        Files.write(Path.of(fileName), upoContent);
        
        System.err.println("\n=== DOWNLOAD COMPLETE ===");
        System.err.println("Saved to: " + fileName);
        System.err.println("Size: " + upoContent.length + " bytes");
        System.err.println("Method: " + downloadMethod);
        
        // Calculate SHA-256 hash
        String hash = calculateSHA256(upoContent);
        
        // Build result
        result.put("status", "SUCCESS");
        result.put("message", "UPO downloaded successfully");
        result.put("fileName", fileName);
        result.put("fileSize", upoContent.length);
        result.put("sha256", hash);
        result.put("downloadMethod", downloadMethod);
        result.put("upoReference", upoRef);
        result.put("sessionReference", ctx.session.referenceNumber);
        
        // Include first few lines of UPO for verification
        String upoText = new String(upoContent, StandardCharsets.UTF_8);
        int previewLength = Math.min(200, upoText.length());
        result.put("preview", upoText.substring(0, previewLength) + "...");
        
        return result;
    }
    
    private static byte[] downloadViaAPI(SessionRuntimeContext ctx, String upoRef) throws Exception {
        String url = normalizeUrl(ctx.runtime.baseUrl) + "/sessions/" + 
                    ctx.session.referenceNumber + "/upo/" + upoRef;
        
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Accept", "application/xml")
                .header("Authorization", "Bearer " + ctx.tokens.accessToken)
                .GET()
                .build();
        
        HttpResponse<byte[]> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofByteArray());
        
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("API returned HTTP " + resp.statusCode());
        }
        
        return resp.body();
    }
    
    private static byte[] downloadViaDirectURL(String directUrl) throws Exception {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(directUrl))
                .GET()
                .build();
        
        HttpResponse<byte[]> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofByteArray());
        
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("Direct URL returned HTTP " + resp.statusCode());
        }
        
        return resp.body();
    }
    
    private static SessionRuntimeContext refreshTokens(SessionRuntimeContext ctx) throws Exception {
        String refreshUrl = normalizeUrl(ctx.runtime.baseUrl) + "/auth/token/refresh";
        
        Map<String, String> requestBody = new LinkedHashMap<>();
        requestBody.put("refreshToken", ctx.tokens.refreshToken);
        
        String requestJson = objectMapper.writeValueAsString(requestBody);
        
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(refreshUrl))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(requestJson))
                .build();
        
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
        
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("Token refresh failed: HTTP " + resp.statusCode() + 
                                           "\nResponse: " + resp.body());
        }
        
        // Parse new tokens
        TokenRefreshResponse refreshResponse = objectMapper.readValue(resp.body(), TokenRefreshResponse.class);
        
        // Update context with new tokens
        ctx.tokens.accessToken = refreshResponse.accessToken.token;
        ctx.tokens.accessTokenValidUntil = refreshResponse.accessToken.validUntil;
        ctx.tokens.refreshToken = refreshResponse.refreshToken.token;
        ctx.tokens.refreshTokenValidUntil = refreshResponse.refreshToken.validUntil;
        
        return ctx;
    }
    
    private static boolean isTokenValid(String validUntil) {
        if (validUntil == null || validUntil.trim().isEmpty()) {
            return false;
        }
        
        try {
            OffsetDateTime expiry = OffsetDateTime.parse(validUntil);
            OffsetDateTime now = OffsetDateTime.now();
            
            // Consider token valid if it expires in more than 30 seconds
            return now.plusSeconds(30).isBefore(expiry);
        } catch (DateTimeParseException e) {
            System.err.println("Warning: Cannot parse token expiry date: " + validUntil);
            return false;
        }
    }
    
    private static String calculateSHA256(byte[] data) throws Exception {
        java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
        byte[] digest = md.digest(data);
        return Base64.getEncoder().encodeToString(digest);
    }
    
    private static String normalizeUrl(String url) {
        if (url == null) return "";
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
    
    private static void printUsage() {
        System.err.println("Usage:");
        System.err.println("  java -jar ksef-download-upo.jar --session-runtime <file.json>");
        System.err.println("");
        System.err.println("Example:");
        System.err.println("  java -jar ksef-download-upo.jar --session-runtime /tmp/session_runtime.json");
        System.err.println("");
        System.err.println("The command will:");
        System.err.println("  1. Check token validity");
        System.err.println("  2. Refresh tokens if expired");
        System.err.println("  3. Download UPO (via API or direct link)");
        System.err.println("  4. Save UPO as XML file");
        System.err.println("  5. Return JSON result with status and metadata");
    }
    
    // ==================== DTO CLASSES ====================
    
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class SessionRuntimeContext {
        public Runtime runtime;
        public Session session;
        public Tokens tokens;
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Runtime {
            public String baseUrl;
            public String integrationMode;
            public String mfPublicKeyPath;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Session {
            public String referenceNumber;
            public String validUntil;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Tokens {
            public String accessToken;
            public String accessTokenValidUntil;
            public String refreshToken;
            public String refreshTokenValidUntil;
        }
    }
    
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TokenRefreshResponse {
        public TokenInfo accessToken;
        public TokenInfo refreshToken;
    }
    
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TokenInfo {
        public String token;
        public String validUntil;
    }
}
