plugins {
    java
    application
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}

application {
    mainClass.set("pl.ksef.auth")
}

repositories {
    mavenCentral()

    maven {
        url = uri("https://maven.pkg.github.com/CIRFMF/ksef-client-java")
		credentials {
			username = project.findProperty("gpr.user") as String?
			password = project.findProperty("gpr.key") as String?
		}
    }
}

dependencies {
	implementation("pl.akmf.ksef-sdk:ksef-client:3.0.8")

    // YAML
    implementation("org.yaml:snakeyaml:2.2")

    // JSON output
    implementation("com.fasterxml.jackson.core:jackson-databind:2.17.1")
}

tasks.register<Jar>("fatJar") {
    group = "build"
    description = "Assembles a runnable fat JAR for auth-wrapper GetTokens"

    archiveBaseName.set("ksef-auth")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.auth.Main"
    }

    from(sourceSets.main.get().output)

    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    // 🔴 KLUCZOWE – USUNIĘCIE PODPISÓW
    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )

    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.register<Jar>("fatJarOpenSession") {
    group = "build"
    description = "Assembles a runnable fat JAR for ONLINE session (SESSION)"

    archiveBaseName.set("ksef-open-session")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.session.Session"
    }

    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )

    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.register<Jar>("fatJarSendInvoice") {
    group = "build"
    description = "Assembles a runnable fat JAR for ONLINE Send Invoice (STATUS)"

    archiveBaseName.set("ksef-send-invoice")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.invoice.Invoice"
    }

    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )

    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.register<Jar>("fatJarCloseSession") {
    group = "build"
    description = "Assembles a runnable fat JAR for ONLINE Close session (SESSION)"

    archiveBaseName.set("ksef-close-session")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.session.SessionClose"
    }

    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )

    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.register<Jar>("fatJarCheckSessionStatus") {
    group = "build"
    description = "Assembles a runnable fat JAR for ONLINE CheckSessionStatus (SESSION)"

    archiveBaseName.set("ksef-check-status")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.session.CheckSessionStatus"
    }

    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )

    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.register<Jar>("fatJarDownloadUPO") {
    group = "build"
    description = "Assembles a runnable fat JAR for downloading UPO"

    archiveBaseName.set("ksef-download-upo")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.session.DownloadUPO"
    }

    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.register<Jar>("fatJarGetReceivedInvoices") {
    group = "build"
    description = "Assembles a runnable fat JAR for querying received invoices"

    archiveBaseName.set("ksef-get-received-invoices")
    archiveClassifier.set("")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "pl.ksef.invoice.GetReceivedInvoices"
    }

    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)

    from({
        configurations.runtimeClasspath.get()
            .filter { it.name.endsWith(".jar") }
            .map { zipTree(it) }
    })

    exclude(
        "META-INF/*.SF",
        "META-INF/*.DSA",
        "META-INF/*.RSA"
    )
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}

tasks.named("build") {
    dependsOn("fatJarGetReceivedInvoices")
}

tasks.named("build") {
	dependsOn("fatJarOpenSession")
    dependsOn("fatJarSendInvoice")
	dependsOn("fatJarCloseSession")
	dependsOn("fatJarCheckSessionStatus")
	dependsOn("fatJarDownloadUPO")
	dependsOn("fatJarGetReceivedInvoices")
}


