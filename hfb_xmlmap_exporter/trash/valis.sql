-- ================================================
-- VERIFICATION SCRIPT: Compare two XML templates
-- ================================================
-- Użycie: Zastąp 123 i 456 rzeczywistymi ID szablonów
-- Przed uruchomieniem: sprawdź czy masz uprawnienia do odczytu
-- ================================================

DO $$
DECLARE
    original_template_id INTEGER := 117;   -- ZASTĄP ID oryginalnego szablonu
    imported_template_id INTEGER := 126;   -- ZASTĄP ID zaimportowanego szablonu
    
    -- Zmienne dla wyników
    orig_template_name TEXT;
    imp_template_name TEXT;
    diff_count INTEGER := 0;
    cnt RECORD;
    nazwa RECORD;
    diff RECORD;
    xsd_diff RECORD;
    child RECORD;
    meta RECORD;
    cp RECORD;
    orig_parent_id INTEGER;
    imp_parent_id INTEGER;
    parent_name TEXT;
BEGIN
    
    RAISE NOTICE '===================================================';
    RAISE NOTICE 'PORÓWNANIE SZABLONÓW XML';
    RAISE NOTICE 'Oryginalny: ID=%, Zaimportowany: ID=%', 
                 original_template_id, imported_template_id;
    RAISE NOTICE '===================================================';
    
    -- 1. PODSTAWOWE INFORMACJE O SZABLONACH
    SELECT name INTO orig_template_name 
    FROM xml_export_template WHERE id = original_template_id;
    
    SELECT name INTO imp_template_name 
    FROM xml_export_template WHERE id = imported_template_id;
    
    RAISE NOTICE '1. NAZWY SZABLONÓW:';
    RAISE NOTICE '   Oryginalny:  "%"', orig_template_name;
    RAISE NOTICE '   Zaimportowany: "%"', imp_template_name;
    RAISE NOTICE '';
    
    -- 2. LICZBY WĘZŁÓW
    RAISE NOTICE '2. LICZBA WĘZŁÓW:';
    
    CREATE TEMP TABLE node_counts AS
    SELECT 
        template_id,
        COUNT(*) as total_nodes,
        COUNT(CASE WHEN parent_id IS NULL THEN 1 END) as root_nodes,
        COUNT(CASE WHEN node_kind = 'element' THEN 1 END) as elements,
        COUNT(CASE WHEN node_kind = 'attribute' THEN 1 END) as attributes,
        COUNT(CASE WHEN node_kind = 'text' THEN 1 END) as text_nodes
    FROM xml_export_node
    WHERE template_id IN (original_template_id, imported_template_id)
    GROUP BY template_id;
    
    FOR cnt IN 
        SELECT * FROM node_counts ORDER BY template_id
    LOOP
        RAISE NOTICE '   Template ID %: % węzłów (root: %, elementy: %, atrybuty: %, tekst: %)',
                     cnt.template_id, cnt.total_nodes, cnt.root_nodes, 
                     cnt.elements, cnt.attributes, cnt.text_nodes;
    END LOOP;
    
    -- 3. SZCZEGÓŁOWE PORÓWNANIE STRUKTURY DRZEWA
    RAISE NOTICE '';
    RAISE NOTICE '3. ANALIZA STRUKTURY DRZEWA:';
    
    -- Tworzymy pełne ścieżki XPath dla każdego węzła
    CREATE TEMP TABLE node_paths AS
    WITH RECURSIVE node_tree AS (
        -- Root nodes
        SELECT 
            id,
            template_id,
            name,
            parent_id,
            name::TEXT as xpath,
            node_kind,
            xsd_type_name,
            1 as level,
            sequence
        FROM xml_export_node
        WHERE parent_id IS NULL
          AND template_id IN (original_template_id, imported_template_id)
        
        UNION ALL
        
        -- Child nodes
        SELECT 
            n.id,
            n.template_id,
            n.name,
            n.parent_id,
            nt.xpath || '/' || n.name as xpath,
            n.node_kind,
            n.xsd_type_name,
            nt.level + 1,
            n.sequence
        FROM xml_export_node n
        INNER JOIN node_tree nt ON n.parent_id = nt.id
        WHERE n.template_id IN (original_template_id, imported_template_id)
    )
    SELECT * FROM node_tree ORDER BY template_id, xpath;
    
    -- 4. ZNAJDŹ SPECJALNIE ELEMENT "Nazwa" (problemowy)
    RAISE NOTICE '';
    RAISE NOTICE '4. ANALIZA ELEMENTU "Nazwa":';
    
    CREATE TEMP TABLE nazwa_analysis AS
    SELECT 
        np.template_id,
        np.name,
        np.xpath,
        np.node_kind,
        np.xsd_type_name,
        np.level,
        parent.name as parent_name,
        parent.xsd_type_name as parent_xsd_type,
        parent.xpath as parent_xpath
    FROM node_paths np
    LEFT JOIN xml_export_node parent ON np.parent_id = parent.id
    WHERE np.name = 'Nazwa'
      AND np.template_id IN (original_template_id, imported_template_id);
    
    IF EXISTS (SELECT 1 FROM nazwa_analysis) THEN
        FOR nazwa IN SELECT * FROM nazwa_analysis ORDER BY template_id
        LOOP
            RAISE NOTICE '   Template ID %: "%"', nazwa.template_id, nazwa.xpath;
            RAISE NOTICE '       Typ: %, Poziom: %, Typ XSD: %', 
                         nazwa.node_kind, nazwa.level, nazwa.xsd_type_name;
            RAISE NOTICE '       Rodzic: "%" (XSD: %)', 
                         nazwa.parent_name, nazwa.parent_xsd_type;
        END LOOP;
    ELSE
        RAISE NOTICE '   ❌ Element "Nazwa" nie znaleziony w żadnym szablonie!';
    END IF;
    
    -- 5. PORÓWNANIE XPATH - RÓŻNICE
    RAISE NOTICE '';
    RAISE NOTICE '5. RÓŻNICE W STRUKTURZE:';
    
    CREATE TEMP TABLE xpath_diff AS
    SELECT 
        xpath,
        BOOL_OR(template_id = original_template_id) as in_original,
        BOOL_OR(template_id = imported_template_id) as in_imported
    FROM node_paths
    GROUP BY xpath
    HAVING COUNT(DISTINCT template_id) < 2
    ORDER BY xpath;
    
    SELECT COUNT(*) INTO diff_count FROM xpath_diff;
    
    IF diff_count > 0 THEN
        RAISE NOTICE '   Znaleziono % różnic w ścieżkach:', diff_count;
        
        FOR diff IN SELECT * FROM xpath_diff LIMIT 20  -- Ogranicz do pierwszych 20
        LOOP
            IF diff.in_original AND NOT diff.in_imported THEN
                RAISE NOTICE '   ➖ BRAKUJE w zaimportowanym: %', diff.xpath;
            ELSIF diff.in_imported AND NOT diff.in_original THEN
                RAISE NOTICE '   ➕ DODATKOWY w zaimportowanym: %', diff.xpath;
            END IF;
        END LOOP;
        
        IF diff_count > 20 THEN
            RAISE NOTICE '   ... i jeszcze % różnic', diff_count - 20;
        END IF;
    ELSE
        RAISE NOTICE '   ✅ Wszystkie ścieżki XPath są identyczne!';
    END IF;
    
    -- 6. PORÓWNANIE TYPÓW XSD
    RAISE NOTICE '';
    RAISE NOTICE '6. TYPY XSD W WĘZŁACH:';
    
    CREATE TEMP TABLE xsd_type_diff AS
    SELECT 
        np.xpath,
        np.name,
        orig.xsd_type_name as orig_type,
        imp.xsd_type_name as imp_type
    FROM (
        SELECT DISTINCT xpath, name 
        FROM node_paths 
        WHERE template_id IN (original_template_id, imported_template_id)
    ) np
    LEFT JOIN node_paths orig ON np.xpath = orig.xpath 
        AND orig.template_id = original_template_id
    LEFT JOIN node_paths imp ON np.xpath = imp.xpath 
        AND imp.template_id = imported_template_id
    WHERE COALESCE(orig.xsd_type_name, '') != COALESCE(imp.xsd_type_name, '');
    
    IF EXISTS (SELECT 1 FROM xsd_type_diff) THEN
        RAISE NOTICE '   Różnice w typach XSD:';
        FOR xsd_diff IN SELECT * FROM xsd_type_diff ORDER BY xpath
        LOOP
            RAISE NOTICE '   %', xsd_diff.xpath;
            RAISE NOTICE '       Oryginalny: "%"', xsd_diff.orig_type;
            RAISE NOTICE '       Zaimportowany: "%"', xsd_diff.imp_type;
        END LOOP;
    ELSE
        RAISE NOTICE '   ✅ Typy XSD są identyczne we wszystkich węzłach!';
    END IF;
    
    -- 7. ANALIZA ELEMENTÓW W TYM SAMYM RODZICU
    RAISE NOTICE '';
    RAISE NOTICE '7. ANALIZA STRUKTURY RODZICA ELEMENTU "Nazwa":';
    
    IF EXISTS (SELECT 1 FROM nazwa_analysis WHERE template_id = original_template_id) THEN
        -- Pobierz ID rodzica elementu "Nazwa" w oryginalnym szablonie
        SELECT parent_id INTO orig_parent_id
        FROM xml_export_node
        WHERE name = 'Nazwa' 
          AND template_id = original_template_id
        LIMIT 1;
        
        SELECT parent_id INTO imp_parent_id
        FROM xml_export_node
        WHERE name = 'Nazwa' 
          AND template_id = imported_template_id
        LIMIT 1;
        
        IF orig_parent_id IS NOT NULL THEN
            RAISE NOTICE '   Dzieci rodzica w ORYGINALNYM (ID: %):', orig_parent_id;
            
            FOR child IN 
                SELECT name, node_kind, sequence, xsd_type_name
                FROM xml_export_node
                WHERE parent_id = orig_parent_id
                  AND template_id = original_template_id
                ORDER BY sequence, id
            LOOP
                RAISE NOTICE '       • % (typ: %, seq: %, xsd: %)', 
                             child.name, child.node_kind, 
                             child.sequence, child.xsd_type_name;
            END LOOP;
        END IF;
        
        IF imp_parent_id IS NOT NULL THEN
            RAISE NOTICE '   Dzieci rodzica w ZAIMPORTOWANYM (ID: %):', imp_parent_id;
            
            FOR child IN 
                SELECT name, node_kind, sequence, xsd_type_name
                FROM xml_export_node
                WHERE parent_id = imp_parent_id
                  AND template_id = imported_template_id
                ORDER BY sequence, id
            LOOP
                RAISE NOTICE '       • % (typ: %, seq: %, xsd: %)', 
                             child.name, child.node_kind, 
                             child.sequence, child.xsd_type_name;
            END LOOP;
        END IF;
    END IF;
    
    -- 8. PODSUMOWANIE
    RAISE NOTICE '';
    RAISE NOTICE '===================================================';
    RAISE NOTICE 'PODSUMOWANIE:';
    RAISE NOTICE '===================================================';
    
    -- Sprawdź podstawowe metadane
    CREATE TEMP TABLE template_meta AS
    SELECT 
        id,
        name,
        root_tag,
        namespace,
        state,
        xsd_target_namespace
    FROM xml_export_template
    WHERE id IN (original_template_id, imported_template_id);
    
    FOR meta IN SELECT * FROM template_meta ORDER BY id
    LOOP
        RAISE NOTICE 'Template ID % ("%"):', meta.id, meta.name;
        RAISE NOTICE '   root_tag: "%", namespace: "%"', meta.root_tag, meta.namespace;
        RAISE NOTICE '   state: "%", xsd_namespace: "%"', meta.state, meta.xsd_target_namespace;
    END LOOP;
    
    -- 9. WAŻNE: SPRAWDŹ DZIECI W KRYTYCZNYM MIEJSCU (gdzie oczekiwane są: NIP, KodUE...)
    RAISE NOTICE '';
    RAISE NOTICE '9. SZUKANIE ELEMENTÓW CHOICE (NIP, KodUE, KodKraju, NrID, BrakID):';
    
    CREATE TEMP TABLE choice_parents AS
    SELECT DISTINCT parent_id
    FROM xml_export_node
    WHERE name IN ('NIP', 'KodUE', 'KodKraju', 'NrID', 'BrakID')
      AND template_id IN (original_template_id, imported_template_id);
    
    FOR cp IN SELECT parent_id FROM choice_parents
    LOOP
        IF cp.parent_id IS NOT NULL THEN
            SELECT name INTO parent_name 
            FROM xml_export_node 
            WHERE id = cp.parent_id;
            
            RAISE NOTICE '   Rodzic elementów choice: "%" (ID: %)', 
                         parent_name, cp.parent_id;
            
            -- Pokaż wszystkie dzieci tego rodzica w oryginalnym
            RAISE NOTICE '      Template % (oryginalny):', original_template_id;
            
            FOR child IN 
                SELECT name, node_kind, sequence
                FROM xml_export_node
                WHERE parent_id = cp.parent_id
                  AND template_id = original_template_id
                ORDER BY sequence
            LOOP
                RAISE NOTICE '          • % (seq: %)', child.name, child.sequence;
            END LOOP;
            
            -- Pokaż wszystkie dzieci tego rodzica w zaimportowanym
            RAISE NOTICE '      Template % (zaimportowany):', imported_template_id;
            
            FOR child IN 
                SELECT name, node_kind, sequence
                FROM xml_export_node
                WHERE parent_id = cp.parent_id
                  AND template_id = imported_template_id
                ORDER BY sequence
            LOOP
                RAISE NOTICE '          • % (seq: %)', child.name, child.sequence;
            END LOOP;
        END IF;
    END LOOP;
    
    -- Sprzątanie tabel tymczasowych
    DROP TABLE IF EXISTS node_counts;
    DROP TABLE IF EXISTS node_paths;
    DROP TABLE IF EXISTS nazwa_analysis;
    DROP TABLE IF EXISTS xpath_diff;
    DROP TABLE IF EXISTS xsd_type_diff;
    DROP TABLE IF EXISTS template_meta;
    DROP TABLE IF EXISTS choice_parents;
    
    RAISE NOTICE '';
    RAISE NOTICE '===================================================';
    RAISE NOTICE 'ANALIZA ZAKOŃCZONA';
    RAISE NOTICE '===================================================';
    
END $$;
