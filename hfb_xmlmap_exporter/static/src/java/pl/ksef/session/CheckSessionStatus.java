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

public class CheckSessionStatus {
    
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            printUsageAndExit();
        }
        
        String baseUrl = null;
        String sessionRef = null;
        String accessToken = null;
        
        // Przetwarzanie argumentów
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--session-runtime":
                    if (i + 1 >= args.length) {
                        System.err.println("ERROR: Missing value for --session-runtime");
                        printUsageAndExit();
                    }
                    Path sessionFile = Path.of(args[++i]);
                    if (!Files.exists(sessionFile)) {
                        System.err.println("ERROR: Session runtime file not found: " + sessionFile);
                        System.exit(1);
                    }
                    
                    // Wczytaj dane z pliku JSON
                    ObjectMapper om = new ObjectMapper();
                    String json = Files.readString(sessionFile);
                    Map<String, Object> ctx = om.readValue(json, Map.class);
                    
                    Map<String, Object> runtime = (Map<String, Object>) ctx.get("runtime");
                    Map<String, Object> session = (Map<String, Object>) ctx.get("session");
                    Map<String, Object> tokens = (Map<String, Object>) ctx.get("tokens");
                    
                    if (runtime != null) baseUrl = (String) runtime.get("baseUrl");
                    if (session != null) sessionRef = (String) session.get("referenceNumber");
                    if (tokens != null) accessToken = (String) tokens.get("accessToken");
                    break;
                    
                case "--base-url":
                    if (i + 1 >= args.length) {
                        System.err.println("ERROR: Missing value for --base-url");
                        printUsageAndExit();
                    }
                    baseUrl = args[++i];
                    break;
                    
                case "--session-ref":
                    if (i + 1 >= args.length) {
                        System.err.println("ERROR: Missing value for --session-ref");
                        printUsageAndExit();
                    }
                    sessionRef = args[++i];
                    break;
                    
                case "--access-token":
                    if (i + 1 >= args.length) {
                        System.err.println("ERROR: Missing value for --access-token");
                        printUsageAndExit();
                    }
                    accessToken = args[++i];
                    break;
                    
                default:
                    System.err.println("ERROR: Unknown argument: " + args[i]);
                    printUsageAndExit();
            }
        }
        
        // Walidacja parametrów
        if (baseUrl == null) {
            System.err.println("ERROR: Missing --base-url parameter");
            printUsageAndExit();
        }
        if (sessionRef == null) {
            System.err.println("ERROR: Missing --session-ref parameter");
            printUsageAndExit();
        }
        if (accessToken == null) {
            System.err.println("ERROR: Missing --access-token parameter");
            printUsageAndExit();
        }
        
        // Sprawdź status
        checkStatus(baseUrl, sessionRef, accessToken);
    }
    
    private static void printUsageAndExit() {
        System.err.println("Usage:");
        System.err.println("  Option 1: --session-runtime <session_runtime.json>");
        System.err.println("  Option 2: --base-url <url> --session-ref <ref> --access-token <token>");
        System.err.println();
        System.err.println("Examples:");
        System.err.println("  java -jar ksef-check-status.jar --session-runtime /tmp/session_runtime.json");
        System.err.println("  java -jar ksef-check-status.jar --base-url https://ksef-test.mf.gov.pl/api/v2 \\");
        System.err.println("    --session-ref 20251222-SO-1D0738F000-23992E3161-41 \\");
        System.err.println("    --access-token eyJhbGciOiJ...");
        System.exit(1);
    }
    
    private static void checkStatus(String baseUrl, String sessionRef, String accessToken) throws Exception {
        String url = normalizeBaseUrl(baseUrl) + "/sessions/" + sessionRef;
        
        System.err.println("=== SESSION STATUS REQUEST ===");
        System.err.println("URL: " + url);
        System.err.println("Session: " + sessionRef);
        
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
        
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        
        System.err.println("=== RESPONSE ===");
        System.err.println("HTTP Status: " + resp.statusCode());
        
        ObjectMapper om = new ObjectMapper();
        Map<String, Object> response;
        
        try {
            response = om.readValue(resp.body(), Map.class);
        } catch (Exception e) {
            System.err.println("Failed to parse JSON response: " + e.getMessage());
            System.err.println("Raw response: " + resp.body());
            return;
        }
        
        // Sformatowana odpowiedź
        String prettyJson = om.writerWithDefaultPrettyPrinter().writeValueAsString(response);
        System.out.println(prettyJson);
        
        // Analiza statusu
        if (response.containsKey("status")) {
            Map<String, Object> status = (Map<String, Object>) response.get("status");
            Object codeObj = status.get("code");
            
            if (codeObj instanceof Number) {
                int code = ((Number) codeObj).intValue();
                System.err.println("\n=== STATUS ANALYSIS ===");
                
                if (code == 100) {
                    System.err.println("✓ Sesja OTWARTA (100) - przyjmuje faktury");
                } else if (code == 110) {
                    System.err.println("✓ Sesja ZAMKNIĘTA (110) - generowanie UPO w toku");
                } else if (code == 120) {
                    System.err.println("✓ Sesja ZAMKNIĘTA (120) - UPO gotowe");
                } else if (code == 130) {
                    System.err.println("✗ Sesja ODRZUCONA (130) - błąd");
                } else if (code == 140) {
                    System.err.println("✗ Sesja ANULOWANA (140)");
                } else {
                    System.err.println("? Nieznany kod statusu: " + code);
                }
            }
        }
        
        // Sprawdź czy UPO jest dostępne
        if (response.containsKey("upo")) {
            Map<String, Object> upo = (Map<String, Object>) response.get("upo");
            System.err.println("\n=== UPO INFORMATION ===");
            
            if (upo.containsKey("pages") && upo.get("pages") != null) {
                System.err.println("✓ UPO jest dostępne do pobrania!");
                // Możesz dodać szczegółowe informacje o stronach UPO
            } else {
                System.err.println("UPO field exists but pages are not ready yet");
            }
        }
    }
    
    private static String normalizeBaseUrl(String url) {
        if (url == null) return "";
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
