-- Broker classification reference (2026-08-08, corrected 2026-08-09).
-- Static dimension table -- Foreign/Local/BUMN doesn't change often, so
-- it's a one-time lookup joined against broker_summary_daily at analysis
-- time, not scraped per request (Indopremier's data-brokersummary.php has
-- no type column at all -- confirmed by fetching the real page, see
-- docs/MASTERPLAN.md).
--
-- 2026-08-08: first pass sourced from a public compiled broker-code list,
-- cross-checked against 17 user-confirmed anchors.
-- 2026-08-09: user supplied the COMPLETE, authoritative Foreign list (32
-- codes) plus confirmed BUMN (4 codes) -- everything else is Local. This
-- superseded 2 real errors from the first pass: RB's name was wrong
-- (had "Nikko Sekuritas", actually "Ina Sekuritas Indonesia", Salim Group
-- affiliated) and BB/Verdhana was wrongly guessed Foreign (it's Local).
-- Also added 7 codes missing from the original public list entirely
-- (BW, CG, DB, FG, LH, ML, MS -- all Foreign, real names not yet known).
--
-- `confidence`: user_confirmed for every row as of 2026-08-09 -- the
-- user's rule (this Foreign list + this BUMN list, else Local) resolves
-- investor_type for all 99 codes. `broker_name` accuracy is a separate,
-- lower-confidence axis (public-source-derived, one already caught wrong)
-- -- don't assume every name is right just because type is confirmed.

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
-- BUMN (4)
('CC','Mandiri Sekuritas','BUMN','user_confirmed',null),
('NI','BNI Sekuritas','BUMN','user_confirmed',null),
('OD','BRI Danareksa Sekuritas','BUMN','user_confirmed',null),
('DX','Bahana Sekuritas','BUMN','user_confirmed',null),
-- Foreign (32)
('AK','UBS Sekuritas Indonesia','Foreign','user_confirmed','Switzerland'),
('ZP','Maybank Sekuritas Indonesia','Foreign','user_confirmed','Malaysia'),
('YP','Mirae Asset Sekuritas Indonesia','Foreign','user_confirmed','Korea'),
('CP','KB Valbury Sekuritas','Foreign','user_confirmed','Korea (KB) JV'),
('BK','J.P. Morgan Sekuritas Indonesia','Foreign','user_confirmed','USA'),
('YU','CGS-CIMB Sekuritas Indonesia','Foreign','user_confirmed','Malaysia/China JV'),
('RX','Macquarie Sekuritas Indonesia','Foreign','user_confirmed','Australia'),
('HD','KGI Sekuritas Indonesia','Foreign','user_confirmed','Taiwan'),
('KK','Phillip Sekuritas Indonesia','Foreign','user_confirmed','Singapore'),
('BQ','Korea Investment and Sekuritas Indonesia','Foreign','user_confirmed','Korea'),
('DR','RHB Sekuritas Indonesia','Foreign','user_confirmed','Malaysia'),
('XA','NH Korindo Sekuritas Indonesia','Foreign','user_confirmed','Korea'),
('KZ','CLSA Sekuritas Indonesia','Foreign','user_confirmed','Hong Kong/CITIC'),
('TP','OCBC Sekuritas Indonesia','Foreign','user_confirmed','Singapore'),
('AG','Kiwoom Sekuritas Indonesia','Foreign','user_confirmed','Korea'),
('AI','UOB Kay Hian Sekuritas','Foreign','user_confirmed','Singapore'),
('LS','Reliance Sekuritas Indonesia Tbk','Foreign','user_confirmed',null),
('RB','Ina Sekuritas Indonesia','Foreign','user_confirmed','Salim Group affiliated -- name corrected 2026-08-09, was wrongly "Nikko"'),
('FS','Yuanta Sekuritas Indonesia','Foreign','user_confirmed','Taiwan'),
('DP','DBS Vickers Sekuritas Indonesia','Foreign','user_confirmed','Singapore'),
('DU','KAF Sekuritas Indonesia','Foreign','user_confirmed',null),
('GI','Webull Sekuritas Indonesia','Foreign','user_confirmed','US/China'),
('AH','Shinhan Sekuritas Indonesia','Foreign','user_confirmed','Korea'),
('BW',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
('CG',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
('CS','Credit Suisse Sekuritas Indonesia','Foreign','user_confirmed','Switzerland'),
('DB',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
('FG',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
('GW','HSBC Sekuritas Indonesia','Foreign','user_confirmed','England'),
('LH',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
('ML',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
('MS',null,'Foreign','user_confirmed','name unverified, code+type from user 2026-08-09'),
-- Local (63) -- everything not listed above as Foreign or BUMN
('AF','Harita Kencana Sekuritas','Local','user_confirmed',null),
('AN','Wanteg Sekuritas','Local','user_confirmed',null),
('AO','Erdikha Elit Sekuritas','Local','user_confirmed',null),
('AP','Pacific Sekuritas Indonesia','Local','user_confirmed',null),
('AR','Binaartha Sekuritas','Local','user_confirmed',null),
('AT','Phintraco Sekuritas','Local','user_confirmed','Phintraco Group'),
('AZ','Sucor Sekuritas','Local','user_confirmed','Sucorinvest Group'),
('BB','Verdhana Sekuritas Indonesia','Local','user_confirmed','corrected 2026-08-09, was wrongly guessed Foreign'),
('BF','Inti Fikasa Sekuritas','Local','user_confirmed',null),
('BR','Trust Sekuritas','Local','user_confirmed',null),
('BS','Equity Sekuritas Indonesia','Local','user_confirmed',null),
('CD','Mega Capital Sekuritas','Local','user_confirmed','CT/Mega Group'),
('DD','Makindo Sekuritas','Local','user_confirmed',null),
('DH','Sinarmas Sekuritas','Local','user_confirmed','Sinarmas Group'),
('DM','Masindo Artha Sekuritas','Local','user_confirmed',null),
('EL','Evergreen Sekuritas Indonesia','Local','user_confirmed',null),
('EP','MNC Sekuritas','Local','user_confirmed','MNC Group'),
('ES','Ekokapital Sekuritas','Local','user_confirmed',null),
('FO','Forte Global Sekuritas','Local','user_confirmed',null),
('FZ','Waterfront Sekuritas Indonesia','Local','user_confirmed',null),
('GA','BNC Sekuritas Indonesia','Local','user_confirmed',null),
('GR','Panin Sekuritas Tbk','Local','user_confirmed','Panin Group'),
('HP','Henan Putihrai Sekuritas','Local','user_confirmed',null),
('ID','Anugerah Sekuritas Indonesia','Local','user_confirmed',null),
('IF','Samuel Sekuritas Indonesia','Local','user_confirmed','Samuel Group'),
('IH','Pacific 2000 Sekuritas','Local','user_confirmed',null),
('II','Danatama Makmur Sekuritas','Local','user_confirmed',null),
('IN','Investindo Nusantara Sekuritas','Local','user_confirmed',null),
('IP','Yugen Bertumbuh Sekuritas','Local','user_confirmed',null),
('IT','Inti Teladan Sekuritas','Local','user_confirmed',null),
('IU','Indo Capital Sekuritas','Local','user_confirmed',null),
('KI','Ciptadana Sekuritas Asia','Local','user_confirmed',null),
('LG','Trimegah Sekuritas Indonesia Tbk','Local','user_confirmed',null),
('MG','Semesta Indovest Sekuritas','Local','user_confirmed',null),
('MI','Victoria Sekuritas Indonesia','Local','user_confirmed','Victoria Group'),
('MK','Ekuator Swarna Sekuritas','Local','user_confirmed',null),
('MU','Minna Padi Investama Sekuritas','Local','user_confirmed',null),
('OK','Net Sekuritas','Local','user_confirmed',null),
('PC','FAC Sekuritas Indonesia','Local','user_confirmed',null),
('PD','Indo Premier Sekuritas','Local','user_confirmed',null),
('PF','Danasakti Sekuritas Indonesia','Local','user_confirmed',null),
('PG','Panca Global Sekuritas','Local','user_confirmed',null),
('PO','Pilarmas Investindo Sekuritas','Local','user_confirmed',null),
('PP','Aldiracita Sekuritas Indonesia','Local','user_confirmed',null),
('PS','Paramitra Alfa Sekuritas','Local','user_confirmed',null),
('RF','Buana Capital Sekuritas','Local','user_confirmed',null),
('RG','Profindo Sekuritas Indonesia','Local','user_confirmed',null),
('RO','Nilai Inti Sekuritas','Local','user_confirmed',null),
('RS','Yulie Sekuritas Indonesia Tbk','Local','user_confirmed',null),
('SA','Elit Sukses Sekuritas','Local','user_confirmed',null),
('SC','IMG Sekuritas','Local','user_confirmed',null),
('SF','Surya Fajar Sekuritas','Local','user_confirmed',null),
('SH','Artha Sekuritas Indonesia','Local','user_confirmed',null),
('SQ','BCA Sekuritas','Local','user_confirmed',null),
('SS','Supra Sekuritas Indonesia','Local','user_confirmed',null),
('TF','Universal Broker Indonesia Sekuritas','Local','user_confirmed',null),
('TS','Dwidana Sakti Sekuritas','Local','user_confirmed',null),
('XC','Ajaib Sekuritas Asia','Local','user_confirmed',null),
('XL','Stockbit Sekuritas Digital','Local','user_confirmed',null),
('YB','Jasa Utama Capital Sekuritas','Local','user_confirmed',null),
('YJ','Lotus Andalan Sekuritas','Local','user_confirmed',null),
('YO','Amantara Sekuritas Indonesia','Local','user_confirmed',null),
('ZR','Bumiputera Sekuritas','Local','user_confirmed',null)
on conflict (broker_code) do update set
  broker_name = excluded.broker_name,
  investor_type = excluded.investor_type,
  confidence = excluded.confidence,
  notes = excluded.notes,
  updated_at = now();
