-- SZYBKA ANALIZA ELEMENTU "Nazwa"
DO $$
DECLARE
    orig_id INTEGER := 117;  -- ZASTĄP
    imp_id INTEGER := 126;   -- ZASTĄP
    rec RECORD;
BEGIN
    RAISE NOTICE 'ANALIZA ELEMENTU "Nazwa"';
    RAISE NOTICE '=========================';
    
    RAISE NOTICE 'ORGYGINALNY szablon (ID: %):', orig_id;
    FOR rec IN 
        SELECT 
            n.name,
            n.xpath,
            n.parent_id,
            p.name as parent_name,
            p.xpath as parent_xpath,
            n.sequence,
            n.node_kind
        FROM xml_export_node n
        LEFT JOIN xml_export_node p ON n.parent_id = p.id
        WHERE n.template_id = orig_id 
          AND n.name = 'Nazwa'
    LOOP
        RAISE NOTICE 'Element: %', rec.name;
        RAISE NOTICE 'Ścieżka: %', rec.xpath;
        RAISE NOTICE 'Rodzic: % (ID: %)', rec.parent_name, rec.parent_id;
        RAISE NOTICE 'Ścieżka rodzica: %', rec.parent_xpath;
        RAISE NOTICE 'Sequence: %, Typ: %', rec.sequence, rec.node_kind;
    END LOOP;
    
    RAISE NOTICE '';
    RAISE NOTICE 'ZAIMPORTOWANY szablon (ID: %):', imp_id;
    FOR rec IN 
        SELECT 
            n.name,
            n.xpath,
            n.parent_id,
            p.name as parent_name,
            p.xpath as parent_xpath,
            n.sequence,
            n.node_kind
        FROM xml_export_node n
        LEFT JOIN xml_export_node p ON n.parent_id = p.id
        WHERE n.template_id = imp_id 
          AND n.name = 'Nazwa'
    LOOP
        RAISE NOTICE 'Element: %', rec.name;
        RAISE NOTICE 'Ścieżka: %', rec.xpath;
        RAISE NOTICE 'Rodzic: % (ID: %)', rec.parent_name, rec.parent_id;
        RAISE NOTICE 'Ścieżka rodzica: %', rec.parent_xpath;
        RAISE NOTICE 'Sequence: %, Typ: %', rec.sequence, rec.node_kind;
    END LOOP;
    
    -- Sprawdź czy w miejscu choice (NIP, KodUE...) jest Nazwa
    RAISE NOTICE '';
    RAISE NOTICE 'SPRAWDZENIE MIEJSCA CHOICE:';
    
    FOR rec IN 
        SELECT DISTINCT p.id, p.name, p.xpath
        FROM xml_export_node n
        JOIN xml_export_node p ON n.parent_id = p.id
        WHERE n.template_id = imp_id 
          AND n.name IN ('NIP', 'KodUE', 'KodKraju', 'NrID', 'BrakID')
    LOOP
        RAISE NOTICE 'Rodzic choice "%" (ID: %, Path: %):', rec.name, rec.id, rec.xpath;
        
        -- Pokaż wszystkie dzieci tego rodzica
        FOR child IN 
            SELECT name, sequence, node_kind
            FROM xml_export_node
            WHERE parent_id = rec.id
              AND template_id = imp_id
            ORDER BY sequence
        LOOP
            RAISE NOTICE '    • % (seq: %, type: %)', 
                         child.name, child.sequence, child.node_kind;
        END LOOP;
    END LOOP;
END $$;
