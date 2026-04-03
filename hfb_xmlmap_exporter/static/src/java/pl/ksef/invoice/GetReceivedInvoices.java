package pl.ksef.invoice;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.ObjectMapper;

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
import java.time.format.DateTimeFormatter;
import java.util.*;

public class GetReceivedInvoices {
    
    private static final ObjectMapper objectMapper = new ObjectMapper();
    private static final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .build();
    
    public static void main(String[] args) {
        Map<String, Object> result = new LinkedHashMap<>();
        
        try {
            // Parse arguments
            Path sessionFile = null;
            String outputFile = null;
            String downloadDir = null;
            String ksefNumber = null;
            int daysBack = 30;
            int pageSize = 50;
            boolean downloadAll = false;
            
            for (int i = 0; i < args.length; i++) {
                switch (args[i]) {
                    case "--session-runtime":
                        sessionFile = Path.of(args[++i]);
                        break;
                    case "--output":
                        outputFile = args[++i];
                        break;
                    case "--days":
                        daysBack = Integer.parseInt(args[++i]);
                        break;
                    case "--page-size":
                        pageSize = Integer.parseInt(args[++i]);
                        break;
                    case "--download":
                        downloadDir = args[++i];
                        break;
                    case "--download-all":
                        downloadAll = true;
                        if (i + 1 < args.length && !args[i + 1].startsWith("--")) {
                            downloadDir = args[++i];
                        } else {
                            downloadDir = "./downloads";
                        }
                        break;
                    case "--ksef-number":
                        ksefNumber = args[++i];
                        break;
                }
            }
            
            if (sessionFile == null) {
                throw new IllegalArgumentException("Missing --session-runtime parameter");
            }
            
            // Load session context
            SessionRuntimeContext ctx = loadSessionContext(sessionFile);
            
            // Check and refresh token if needed
            if (!isTokenValid(ctx.tokens.accessTokenValidUntil)) {
                System.err.println("⚠️ Token expired. Refreshing...");
                ctx = refreshTokens(ctx);
            }
            
            if (ksefNumber != null) {
                // Pobierz pojedynczą fakturę przez ksefNumber
                System.err.println("=== DOWNLOADING SINGLE INVOICE ===");
                System.err.println("KSeF Number: " + ksefNumber);
                
                byte[] invoiceXml = getInvoiceByKsefNumber(
                    ctx.runtime.baseUrl, 
                    ctx.tokens.accessToken, 
                    ksefNumber
                );
                
                result.put("status", "SUCCESS");
                result.put("ksefNumber", ksefNumber);
                result.put("invoiceSize", invoiceXml.length);
                
                // Zapisz do pliku jeśli podano katalog
                if (downloadDir != null) {
                    Path dir = Path.of(downloadDir);
                    Files.createDirectories(dir);
                    
                    String fileName = sanitizeFileName(ksefNumber) + ".xml";
                    Path filePath = dir.resolve(fileName);
                    
                    Files.write(filePath, invoiceXml);
                    result.put("savedTo", filePath.toString());
                    System.err.println("✅ Invoice saved to: " + filePath);
                }
                
            } else {
                // Query received invoices (oryginalna funkcjonalność)
                List<Map<String, Object>> allInvoices = queryReceivedInvoices(
                    ctx.runtime.baseUrl, 
                    ctx.tokens.accessToken, 
                    daysBack, 
                    pageSize
                );
                
                // Prepare result
                result.put("status", "SUCCESS");
                result.put("invoiceCount", allInvoices.size());
                result.put("queryDateRange", daysBack + " days back");
                result.put("invoices", allInvoices);
                
                // Pobierz pełne faktury jeśli requested
                List<Map<String, Object>> downloadResults = null;
                if (downloadAll && allInvoices.size() > 0) {
                    System.err.println("=== DOWNLOADING FULL INVOICES ===");
                    downloadResults = downloadAllInvoices(ctx, allInvoices, downloadDir);
                    result.put("downloadResults", downloadResults);
                }
                
                // Save to file if requested
                if (outputFile != null) {
                    Map<String, Object> fileOutput = new LinkedHashMap<>();
                    fileOutput.put("queryTimestamp", OffsetDateTime.now().toString());
                    fileOutput.put("nip", ctx.context != null ? ctx.context.nip : "UNKNOWN");
                    fileOutput.put("invoices", allInvoices);
                    
                    Files.writeString(
                        Path.of(outputFile),
                        objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(fileOutput),
                        StandardCharsets.UTF_8
                    );
                    
                    result.put("outputFile", outputFile);
                    System.err.println("✅ Metadata saved to: " + outputFile);
                }
            }
            
        } catch (Exception e) {
            result.put("status", "ERROR");
            result.put("message", e.getMessage());
            result.put("errorType", e.getClass().getSimpleName());
            
            StringWriter sw = new StringWriter();
            e.printStackTrace(new PrintWriter(sw));
            result.put("stackTrace", sw.toString());
        }
        
        // Output result
        try {
            System.out.println(objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(result));
        } catch (Exception e) {
            System.err.println("FATAL: Could not output JSON: " + e.getMessage());
            System.err.println("Result was: " + result.toString());
        }
    }
    
    private static byte[] getInvoiceByKsefNumber(
            String baseUrl, 
            String accessToken, 
            String ksefNumber) throws Exception {
        
        String url = normalizeUrl(baseUrl) + "/invoices/ksef/" + ksefNumber;
        
        System.err.println("URL: " + url);
        
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Accept", "application/xml")
                .header("Authorization", "Bearer " + accessToken)
                .GET()
                .build();
        
        HttpResponse<byte[]> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofByteArray());
        
        System.err.println("HTTP Status: " + resp.statusCode());
        
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("Download failed: HTTP " + resp.statusCode() + 
                "\nResponse: " + new String(resp.body(), StandardCharsets.UTF_8));
        }
        
        byte[] invoiceXml = resp.body();
        System.err.println("✅ Invoice downloaded, size: " + invoiceXml.length + " bytes");
        
        // Optional: validate XML
        String xmlStr = new String(invoiceXml, StandardCharsets.UTF_8);
        if (!xmlStr.trim().startsWith("<?xml")) {
            System.err.println("⚠️ Warning: Response doesn't look like valid XML");
        }
        
        return invoiceXml;
    }
    
    private static List<Map<String, Object>> downloadAllInvoices(
            SessionRuntimeContext ctx,
            List<Map<String, Object>> invoices,
            String downloadDir) throws Exception {
        
        Path dir = Path.of(downloadDir);
        Files.createDirectories(dir);
        
        List<Map<String, Object>> results = new ArrayList<>();
        int successCount = 0;
        int failCount = 0;
        
        for (int i = 0; i < invoices.size(); i++) {
            Map<String, Object> invoice = invoices.get(i);
            String ksefNum = (String) invoice.get("ksefNumber");
            String invoiceNum = (String) invoice.get("invoiceNumber");
            
            System.err.print("[" + (i+1) + "/" + invoices.size() + "] " + 
                ksefNum + " (" + invoiceNum + ")... ");
            
            Map<String, Object> downloadResult = new LinkedHashMap<>();
            downloadResult.put("ksefNumber", ksefNum);
            downloadResult.put("invoiceNumber", invoiceNum);
            downloadResult.put("index", i);
            
            try {
                byte[] invoiceXml = getInvoiceByKsefNumber(
                    ctx.runtime.baseUrl, 
                    ctx.tokens.accessToken, 
                    ksefNum
                );
                
                // Generate safe filename
                String fileName = String.format("%03d_%s_%s.xml",
                    i + 1,
                    sanitizeFileName(invoiceNum),
                    sanitizeFileName(ksefNum)
                );
                
                Path filePath = dir.resolve(fileName);
                Files.write(filePath, invoiceXml);
                
                downloadResult.put("status", "SUCCESS");
                downloadResult.put("file", fileName);
                downloadResult.put("size", invoiceXml.length);
                successCount++;
                
                System.err.println("✅");
                
            } catch (Exception e) {
                downloadResult.put("status", "ERROR");
                downloadResult.put("error", e.getMessage());
                failCount++;
                
                System.err.println("❌ " + e.getMessage());
            }
            
            results.add(downloadResult);
            
            // Small delay to avoid rate limiting
            if (i < invoices.size() - 1) {
                Thread.sleep(100);
            }
        }
        
        System.err.println("=== DOWNLOAD SUMMARY ===");
        System.err.println("Success: " + successCount);
        System.err.println("Failed: " + failCount);
        System.err.println("Total: " + invoices.size());
        
        return results;
    }
    
    private static List<Map<String, Object>> queryReceivedInvoices(
            String baseUrl, 
            String accessToken, 
            int daysBack,
            int pageSize) throws Exception {
        
        String url = normalizeUrl(baseUrl) + "/invoices/query/metadata";
        
        System.err.println("=== QUERYING RECEIVED INVOICES ===");
        System.err.println("URL: " + url);
        System.err.println("Date range: last " + daysBack + " days");
        
        // Prepare request body for RECEIVED invoices (SubjectType = SUBJECT2)
        Map<String, Object> requestBody = new LinkedHashMap<>();
        
        // Date range filter
        Map<String, Object> dateRange = new LinkedHashMap<>();
        dateRange.put("dateType", "INVOICING"); // INVOICING, ISSUE, DUE
        dateRange.put("from", OffsetDateTime.now().minusDays(daysBack).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        dateRange.put("to", OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        
        // Subject type = SUBJECT2 for received invoices
        requestBody.put("subjectType", "SUBJECT2");
        requestBody.put("dateRange", dateRange);
        
        // Optional: add more filters
        // requestBody.put("invoiceNumber", "FV/2025/123");
        // requestBody.put("subjectBy", Map.of("type", "COMPANY", "identifier", Map.of("type", "NIP", "value", "1234567890")));
        
        String requestJson = objectMapper.writeValueAsString(requestBody);
        System.err.println("Request body:");
        System.err.println(objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(requestBody));
        
        List<Map<String, Object>> allInvoices = new ArrayList<>();
        int pageOffset = 0;
        String continuationToken = null;
        boolean hasMore = true;
        
        while (hasMore) {
            // Build URL with pagination
            String requestUrl = url;
            if (continuationToken != null) {
                requestUrl += "?continuationToken=" + continuationToken + "&pageSize=" + pageSize;
            } else {
                requestUrl += "?pageOffset=" + pageOffset + "&pageSize=" + pageSize;
            }
            
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(requestUrl))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .header("Authorization", "Bearer " + accessToken)
                    .POST(HttpRequest.BodyPublishers.ofString(requestJson))
                    .build();
            
            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            
            System.err.println("Page " + (pageOffset / pageSize + 1) + " - HTTP Status: " + resp.statusCode());
            
            if (resp.statusCode() != 200) {
                throw new IllegalStateException("Query failed: HTTP " + resp.statusCode() + "\nResponse: " + resp.body());
            }
            
            // Parse response
            Map<String, Object> response = objectMapper.readValue(resp.body(), Map.class);
            
            // Get invoices from this page
            List<Map<String, Object>> pageInvoices = (List<Map<String, Object>>) response.get("invoices");
            if (pageInvoices != null) {
                allInvoices.addAll(pageInvoices);
                System.err.println("  Found " + pageInvoices.size() + " invoices on this page");
            }
            
            // Check for continuation token
            continuationToken = (String) response.get("continuationToken");
            if (continuationToken == null || continuationToken.isEmpty()) {
                hasMore = false;
            } else {
                pageOffset += pageSize;
                System.err.println("  Continuation token present, fetching next page...");
            }
            
            // Safety limit
            if (pageOffset > 1000) {
                System.err.println("⚠️  Safety limit reached (1000+ invoices)");
                break;
            }
        }
        
        System.err.println("✅ Total invoices found: " + allInvoices.size());
        return allInvoices;
    }
    
    private static SessionRuntimeContext loadSessionContext(Path file) throws Exception {
        return objectMapper.readValue(Files.newInputStream(file), SessionRuntimeContext.class);
    }
    
    private static boolean isTokenValid(String validUntil) {
        if (validUntil == null || validUntil.trim().isEmpty()) {
            return false;
        }
        
        try {
            OffsetDateTime expiry = OffsetDateTime.parse(validUntil);
            return OffsetDateTime.now().plusSeconds(30).isBefore(expiry);
        } catch (Exception e) {
            return false;
        }
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
            throw new IllegalStateException("Token refresh failed: HTTP " + resp.statusCode());
        }
        
        TokenRefreshResponse refreshResponse = objectMapper.readValue(resp.body(), TokenRefreshResponse.class);
        
        // Update context
        ctx.tokens.accessToken = refreshResponse.accessToken.token;
        ctx.tokens.accessTokenValidUntil = refreshResponse.accessToken.validUntil;
        ctx.tokens.refreshToken = refreshResponse.refreshToken.token;
        ctx.tokens.refreshTokenValidUntil = refreshResponse.refreshToken.validUntil;
        
        return ctx;
    }
    
    private static String normalizeUrl(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
    
    private static String sanitizeFileName(String name) {
        if (name == null) return "unknown";
        return name.replaceAll("[^a-zA-Z0-9._-]", "_").replaceAll("_+", "_");
    }
    
    // DTO Classes
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class SessionRuntimeContext {
        public Runtime runtime;
        public Context context;
        public Session session;
        public Tokens tokens;
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Runtime {
            public String baseUrl;
            public String integrationMode;
        }
        
        @JsonIgnoreProperties(ignoreUnknown = true)
        public static class Context {
            public String nip;
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
