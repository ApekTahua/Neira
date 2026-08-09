-- Broker classification reference (2026-08-08). Static dimension table --
-- Foreign/Local/BUMN doesn't change often, so it's a one-time lookup
-- joined against broker_summary_daily at analysis time, not scraped per
-- request (Indopremier's data-brokersummary.php has no type column at
-- all -- confirmed by fetching the real page, see docs/MASTERPLAN.md).
--
-- Sourced from a public compiled broker-code list, cross-checked against
-- 17 user-confirmed anchors (2026-08-08) -- 3 mismatches found and fixed
-- (DX/Bahana and OD's siblings are BUMN not "Local", YU/CGS-CIMB and
-- HD/KGI are Foreign not "Local" -- the source's own Local/Foreign tags
-- were unreliable, only its code->company-name mapping was trusted).
--
-- `confidence`: user_confirmed (your 17 examples) / high (unambiguous
-- global brand or BUMN name) / medium (plausible default, unverified) /
-- low (genuinely uncertain, review before trusting in analysis).

create table if not exists brokers (
  broker_code text primary key,
  broker_name text,
  investor_type text not null check (investor_type in ('Foreign', 'Local', 'BUMN')),
  confidence text not null check (confidence in ('user_confirmed', 'high', 'medium', 'low')),
  notes text,
  updated_at timestamptz not null default now()
);

alter table brokers enable row level security;
drop policy if exists brokers_select_anon on brokers;
create policy brokers_select_anon on brokers
  for select to anon, authenticated using (true);

insert into brokers (broker_code, broker_name, investor_type, confidence, notes) values
('AF','Harita Kencana Sekuritas','Local','high',null),
('AG','Kiwoom Sekuritas Indonesia','Foreign','high','Korea'),
('AH','Shinhan Sekuritas Indonesia','Foreign','high','Korea'),
('AI','UOB Kay Hian Sekuritas','Foreign','high','Singapore'),
('AK','UBS Sekuritas Indonesia','Foreign','high','Switzerland'),
('AN','Wanteg Sekuritas','Local','medium',null),
('AO','Erdikha Elit Sekuritas','Local','high',null),
('AP','Pacific Sekuritas Indonesia','Local','medium',null),
('AR','Binaartha Sekuritas','Local','high',null),
('AT','Phintraco Sekuritas','Local','high','Phintraco Group'),
('AZ','Sucor Sekuritas','Local','high','Sucorinvest Group'),
('BB','Verdhana Sekuritas Indonesia','Foreign','low','ex-CLSA lineage, ownership ambiguous -- REVIEW'),
('BF','Inti Fikasa Sekuritas','Local','medium',null),
('BK','J.P. Morgan Sekuritas Indonesia','Foreign','user_confirmed','USA'),
('BQ','Korea Investment and Sekuritas Indonesia','Foreign','user_confirmed','Korea'),
('BR','Trust Sekuritas','Local','medium',null),
('BS','Equity Sekuritas Indonesia','Local','medium',null),
('CC','Mandiri Sekuritas','BUMN','user_confirmed',null),
('CD','Mega Capital Sekuritas','Local','high','CT/Mega Group'),
('CP','KB Valbury Sekuritas','Foreign','user_confirmed','Korea (KB) JV'),
('CS','Credit Suisse Sekuritas Indonesia','Foreign','high','Switzerland -- source mislabeled Local'),
('DD','Makindo Sekuritas','Local','medium',null),
('DH','Sinarmas Sekuritas','Local','high','Sinarmas Group'),
('DM','Masindo Artha Sekuritas','Local','medium',null),
('DP','DBS Vickers Sekuritas Indonesia','Foreign','high','Singapore'),
('DR','RHB Sekuritas Indonesia','Foreign','high','Malaysia -- source mislabeled Local'),
('DU','KAF Sekuritas Indonesia','Local','medium',null),
('DX','Bahana Sekuritas','BUMN','user_confirmed','source mislabeled Local'),
('EL','Evergreen Sekuritas Indonesia','Local','medium',null),
('EP','MNC Sekuritas','Local','high','MNC Group'),
('ES','Ekokapital Sekuritas','Local','medium',null),
('FO','Forte Global Sekuritas','Local','medium',null),
('FS','Yuanta Sekuritas Indonesia','Foreign','high','Taiwan'),
('FZ','Waterfront Sekuritas Indonesia','Local','medium',null),
('GA','BNC Sekuritas Indonesia','Local','medium',null),
('GI','Webull Sekuritas Indonesia','Foreign','high','US/China'),
('GR','Panin Sekuritas Tbk','Local','high','Panin Group'),
('GW','HSBC Sekuritas Indonesia','Foreign','high','England'),
('HD','KGI Sekuritas Indonesia','Foreign','user_confirmed','Taiwan -- source mislabeled Local'),
('HP','Henan Putihrai Sekuritas','Local','high',null),
('ID','Anugerah Sekuritas Indonesia','Local','medium',null),
('IF','Samuel Sekuritas Indonesia','Local','high','Samuel Group'),
('IH','Pacific 2000 Sekuritas','Local','medium',null),
('II','Danatama Makmur Sekuritas','Local','medium',null),
('IN','Investindo Nusantara Sekuritas','Local','medium',null),
('IP','Yugen Bertumbuh Sekuritas','Local','medium',null),
('IT','Inti Teladan Sekuritas','Local','medium',null),
('IU','Indo Capital Sekuritas','Local','medium',null),
('KI','Ciptadana Sekuritas Asia','Local','low','ownership ambiguous -- REVIEW'),
('KK','Phillip Sekuritas Indonesia','Foreign','high','Singapore'),
('KZ','CLSA Sekuritas Indonesia','Foreign','high','Hong Kong/CITIC'),
('LG','Trimegah Sekuritas Indonesia Tbk','Local','user_confirmed',null),
('LS','Reliance Sekuritas Indonesia Tbk','Local','high',null),
('MG','Semesta Indovest Sekuritas','Local','user_confirmed',null),
('MI','Victoria Sekuritas Indonesia','Local','high','Victoria Group'),
('MK','Ekuator Swarna Sekuritas','Local','medium',null),
('MU','Minna Padi Investama Sekuritas','Local','high',null),
('NI','BNI Sekuritas','BUMN','user_confirmed',null),
('OD','BRI Danareksa Sekuritas','BUMN','user_confirmed',null),
('OK','Net Sekuritas','Local','medium',null),
('PC','FAC Sekuritas Indonesia','Local','medium',null),
('PD','Indo Premier Sekuritas','Local','user_confirmed',null),
('PF','Danasakti Sekuritas Indonesia','Local','medium',null),
('PG','Panca Global Sekuritas','Local','medium',null),
('PO','Pilarmas Investindo Sekuritas','Local','medium',null),
('PP','Aldiracita Sekuritas Indonesia','Local','medium',null),
('PS','Paramitra Alfa Sekuritas','Local','medium',null),
('RB','Nikko Sekuritas Indonesia','Foreign','low','legacy Japanese branding, current ownership unclear -- REVIEW'),
('RF','Buana Capital Sekuritas','Local','medium',null),
('RG','Profindo Sekuritas Indonesia','Local','medium',null),
('RO','Nilai Inti Sekuritas','Local','medium',null),
('RS','Yulie Sekuritas Indonesia Tbk','Local','medium',null),
('RX','Macquarie Sekuritas Indonesia','Foreign','user_confirmed','Australia'),
('SA','Elit Sukses Sekuritas','Local','medium',null),
('SC','IMG Sekuritas','Local','medium',null),
('SF','Surya Fajar Sekuritas','Local','medium',null),
('SH','Artha Sekuritas Indonesia','Local','medium',null),
('SQ','BCA Sekuritas','Local','user_confirmed',null),
('SS','Supra Sekuritas Indonesia','Local','medium',null),
('TF','Universal Broker Indonesia Sekuritas','Local','medium',null),
('TP','OCBC Sekuritas Indonesia','Foreign','high','Singapore -- source mislabeled Local'),
('TS','Dwidana Sakti Sekuritas','Local','medium',null),
('XA','NH Korindo Sekuritas Indonesia','Foreign','high','Korea'),
('XC','Ajaib Sekuritas Asia','Local','user_confirmed',null),
('XL','Stockbit Sekuritas Digital','Local','user_confirmed',null),
('YB','Jasa Utama Capital Sekuritas','Local','medium',null),
('YJ','Lotus Andalan Sekuritas','Local','medium',null),
('YO','Amantara Sekuritas Indonesia','Local','medium',null),
('YP','Mirae Asset Sekuritas Indonesia','Foreign','high','Korea'),
('YU','CGS-CIMB Sekuritas Indonesia','Foreign','user_confirmed','Malaysia/China JV -- source mislabeled Local'),
('ZP','Maybank Sekuritas Indonesia','Foreign','high','Malaysia'),
('ZR','Bumiputera Sekuritas','Local','medium',null)
on conflict (broker_code) do update set
  broker_name = excluded.broker_name,
  investor_type = excluded.investor_type,
  confidence = excluded.confidence,
  notes = excluded.notes,
  updated_at = now();
