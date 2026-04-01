package pl.ksef.invoice;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import java.security.MessageDigest;
import java.time.Duration;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

public class Invoice {

    // =============================
    // MAIN
    // =============================
	public static void main(String[] args) throws Exception {
		Args a = Args.parse(args);
		SessionRuntimeContext ctx = loadSessionRuntimeContext(a.sessionRuntime);
		validateContext(ctx);

		byte[] invoiceXml = Files.readAllBytes(a.invoiceFile);

		// --- AES encryption ---
		byte[] encryptedInvoice = encryptAesCbc(
				invoiceXml,
				ctx.encryptionDebug.getAesKeyBytes(),
				ctx.encryptionDebug.getIvBytes()
		);

		String b64EncryptedInvoice = Base64.getEncoder().encodeToString(encryptedInvoice);
		
		// Oblicz hashe i rozmiary
		String invoiceHash = sha256Base64(invoiceXml);
		int invoiceSize = invoiceXml.length;
		String encryptedInvoiceHash = sha256Base64(encryptedInvoice);
		int encryptedInvoiceSize = encryptedInvoice.length;

		// DEBUG
		System.err.println("=== DEBUG: Invoice hashes ===");
		System.err.println("Original invoice hash (Base64): " + invoiceHash);
		System.err.println("Original invoice size: " + invoiceSize + " bytes");
		System.err.println("Encrypted invoice hash (Base64): " + encryptedInvoiceHash);
		System.err.println("Encrypted invoice size: " + encryptedInvoiceSize + " bytes");

		// --- POST /sessions/online/{ref}/invoices ---
		String url = normalizeBaseUrl(ctx.runtime.baseUrl)
				+ "/sessions/online/"
				+ ctx.session.referenceNumber
				+ "/invoices";

		Map<String, Object> payload = new LinkedHashMap<>();
		payload.put("invoiceHash", invoiceHash);
		payload.put("invoiceSize", invoiceSize);
		payload.put("encryptedInvoiceHash", encryptedInvoiceHash);
		payload.put("encryptedInvoiceSize", encryptedInvoiceSize);
		payload.put("encryptedInvoiceContent", b64EncryptedInvoice);

		ObjectMapper om = new ObjectMapper();
		String jsonBody = om.writeValueAsString(payload);
		
		// DEBUG payload
		System.err.println("=== DEBUG: Payload to send ===");
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

		HttpResponse<String> resp =
				http.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

		if (resp.statusCode() != 201) {
			Map<String, Object> err = new LinkedHashMap<>();
			err.put("httpStatus", resp.statusCode());
			err.put("body", resp.body());
			System.out.println(om.writerWithDefaultPrettyPrinter().writeValueAsString(err));
			return;
		}

		Map<?, ?> apiResp = om.readValue(resp.body(), Map.class);

		Map<String, Object> out = new LinkedHashMap<>();
		out.put("sessionReferenceNumber", ctx.session.referenceNumber);
		out.put("invoiceReferenceNumber", apiResp.get("referenceNumber"));
		out.put("hashSHA256", invoiceHash);

		System.out.println(
				om.writerWithDefaultPrettyPrinter().writeValueAsString(out)
		);
	}


    // =============================
    // CRYPTO
    // =============================
    static byte[] encryptAesCbc(byte[] data, byte[] key, byte[] iv) throws Exception {
        Cipher c = Cipher.getInstance("AES/CBC/PKCS5Padding");
        c.init(
                Cipher.ENCRYPT_MODE,
                new SecretKeySpec(key, "AES"),
                new IvParameterSpec(iv)
        );
        return c.doFinal(data);
    }

	static String sha256Base64(byte[] data) throws Exception {
		MessageDigest md = MessageDigest.getInstance("SHA-256");
		byte[] digest = md.digest(data);
		return Base64.getEncoder().encodeToString(digest);
	}

    static String sha256Hex(byte[] data) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] digest = md.digest(data);
        StringBuilder sb = new StringBuilder();
        for (byte b : digest) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    // =============================
    // CONTEXT
    // =============================
    static SessionRuntimeContext loadSessionRuntimeContext(Path p) throws IOException {
        ObjectMapper om = new ObjectMapper();
        return om.readValue(Files.newInputStream(p), SessionRuntimeContext.class);
    }

    static void validateContext(SessionRuntimeContext ctx) {
        if (ctx == null
                || ctx.runtime == null
                || ctx.session == null
                || ctx.encryptionDebug == null
                || ctx.tokens == null) {
            throw new IllegalStateException("Invalid session runtime context");
        }
    }

    static String normalizeBaseUrl(String u) {
        return u.endsWith("/") ? u.substring(0, u.length() - 1) : u;
    }

    // =============================
    // ARGS
    // =============================
    static class Args {
        Path sessionRuntime;
        Path invoiceFile;

        static Args parse(String[] args) {
            Args a = new Args();
            for (int i = 0; i < args.length; i++) {
                if ("--session-runtime".equals(args[i])) {
                    a.sessionRuntime = Path.of(args[++i]);
                } else if ("--invoice".equals(args[i])) {
                    a.invoiceFile = Path.of(args[++i]);
                }
            }
            if (a.sessionRuntime == null || a.invoiceFile == null) {
                throw new IllegalArgumentException(
                        "Usage: --session-runtime <file> --invoice <file>"
                );
            }
            return a;
        }
    }

	// =============================
	// DTOs
	// =============================
	@JsonIgnoreProperties(ignoreUnknown = true)
	public static class SessionRuntimeContext {
		public Runtime runtime;
		public Session session;
		public EncryptionDebug encryptionDebug;  // ZMIANA: encryption → encryptionDebug
		public Tokens tokens;
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public static class EncryptionDebug {
		public String aesKeyBase64;
		public String ivBase64;
		
		public byte[] getAesKeyBytes() {
			return Base64.getDecoder().decode(this.aesKeyBase64);
		}
		
		public byte[] getIvBytes() {
			return Base64.getDecoder().decode(this.ivBase64);
		}
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public static class Runtime {
		public String baseUrl;
		// Opcjonalnie dodaj pozostałe pola jeśli są potrzebne:
		// public String integrationMode;
		// public String mfPublicKeyPath;
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public static class Session {
		public String referenceNumber;
		public String validUntil;
	}

	// NOWA WERSJA:
	@JsonIgnoreProperties(ignoreUnknown = true)
	public static class Encryption {
		private String aesKeyBase64;
		private String ivBase64;
		
		// Gettery i settery dla Jacksona
		public String getAesKeyBase64() {
			return aesKeyBase64;
		}
		
		public void setAesKeyBase64(String aesKeyBase64) {
			this.aesKeyBase64 = aesKeyBase64;
		}
		
		public String getIvBase64() {
			return ivBase64;
		}
		
		public void setIvBase64(String ivBase64) {
			this.ivBase64 = ivBase64;
		}
		
		// Metody pomocnicze
		public byte[] getAesKeyBytes() {
			return Base64.getDecoder().decode(this.aesKeyBase64);
		}
		
		public byte[] getIvBytes() {
			return Base64.getDecoder().decode(this.ivBase64);
		}
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public static class Tokens {
		public String accessToken;
		public String accessTokenValidUntil;
		public String refreshToken;
		public String refreshTokenValidUntil;
	}

}

