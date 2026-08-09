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
-- (BW, CG, DB, FG, LH, ML, MS -- all Foreign). 5 of those 7 named by the
-- user same day (BW=BNP Paribas, CG=Citigroup, FG=Nomura, LH=Royal
-- Investium, MS=Morgan Stanley); DB and ML still unnamed.
--
-- `confidence` column dropped 2026-08-09 (user call -- every row's
-- investor_type is user_confirmed now, the column stopped carrying
-- information). `broker_name` accuracy is still a separate axis from
-- `investor_type` accuracy -- one name (RB) was already caught wrong once,
-- don't assume every name here is right just because the type is solid.

create table if not exists brokers (
  broker_code text primary key,
  broker_name text,
  investor_type text not null check (investor_type in ('Foreign', 'Local', 'BUMN')),
  notes text,
  updated_at timestamptz not null default now()
);

alter table brokers enable row level security;
drop policy if exists brokers_select_anon on brokers;
create policy brokers_select_anon on brokers
  for select to anon, authenticated using (true);

insert into brokers (broker_code, broker_name, investor_type, notes) values
-- BUMN (4)
('CC','Mandiri Sekuritas','BUMN',null),
('NI','BNI Sekuritas','BUMN',null),
('OD','BRI Danareksa Sekuritas','BUMN',null),
('DX','Bahana Sekuritas','BUMN',null),
-- Foreign (32)
('AK','UBS Sekuritas Indonesia','Foreign','Switzerland'),
('ZP','Maybank Sekuritas Indonesia','Foreign','Malaysia'),
('YP','Mirae Asset Sekuritas Indonesia','Foreign','Korea'),
('CP','KB Valbury Sekuritas','Foreign','Korea (KB) JV'),
('BK','J.P. Morgan Sekuritas Indonesia','Foreign','USA'),
('YU','CGS-CIMB Sekuritas Indonesia','Foreign','Malaysia/China JV'),
('RX','Macquarie Sekuritas Indonesia','Foreign','Australia'),
('HD','KGI Sekuritas Indonesia','Foreign','Taiwan'),
('KK','Phillip Sekuritas Indonesia','Foreign','Singapore'),
('BQ','Korea Investment and Sekuritas Indonesia','Foreign','Korea'),
('DR','RHB Sekuritas Indonesia','Foreign','Malaysia'),
('XA','NH Korindo Sekuritas Indonesia','Foreign','Korea'),
('KZ','CLSA Sekuritas Indonesia','Foreign','Hong Kong/CITIC'),
('TP','OCBC Sekuritas Indonesia','Foreign','Singapore'),
('AG','Kiwoom Sekuritas Indonesia','Foreign','Korea'),
('AI','UOB Kay Hian Sekuritas','Foreign','Singapore'),
('LS','Reliance Sekuritas Indonesia Tbk','Foreign',null),
('RB','Ina Sekuritas Indonesia','Foreign','Salim Group affiliated -- name corrected 2026-08-09, was wrongly "Nikko"'),
('FS','Yuanta Sekuritas Indonesia','Foreign','Taiwan'),
('DP','DBS Vickers Sekuritas Indonesia','Foreign','Singapore'),
('DU','KAF Sekuritas Indonesia','Foreign',null),
('GI','Webull Sekuritas Indonesia','Foreign','US/China'),
('AH','Shinhan Sekuritas Indonesia','Foreign','Korea'),
('BW','BNP Paribas Sekuritas Indonesia','Foreign','France'),
('CG','Citigroup Sekuritas Indonesia','Foreign','USA'),
('CS','Credit Suisse Sekuritas Indonesia','Foreign','Switzerland'),
('DB',null,'Foreign','name unverified, code+type from user 2026-08-09'),
('FG','Nomura Sekuritas Indonesia','Foreign','Japan'),
('GW','HSBC Sekuritas Indonesia','Foreign','England'),
('LH','Royal Investium Sekuritas','Foreign',null),
('ML',null,'Foreign','name unverified, code+type from user 2026-08-09'),
('MS','Morgan Stanley Sekuritas Indonesia','Foreign','USA'),
-- Local (63) -- everything not listed above as Foreign or BUMN
('AF','Harita Kencana Sekuritas','Local',null),
('AN','Wanteg Sekuritas','Local',null),
('AO','Erdikha Elit Sekuritas','Local',null),
('AP','Pacific Sekuritas Indonesia','Local',null),
('AR','Binaartha Sekuritas','Local',null),
('AT','Phintraco Sekuritas','Local','Phintraco Group'),
('AZ','Sucor Sekuritas','Local','Sucorinvest Group'),
('BB','Verdhana Sekuritas Indonesia','Local','corrected 2026-08-09, was wrongly guessed Foreign'),
('BF','Inti Fikasa Sekuritas','Local',null),
('BR','Trust Sekuritas','Local',null),
('BS','Equity Sekuritas Indonesia','Local',null),
('CD','Mega Capital Sekuritas','Local','CT/Mega Group'),
('DD','Makindo Sekuritas','Local',null),
('DH','Sinarmas Sekuritas','Local','Sinarmas Group'),
('DM','Masindo Artha Sekuritas','Local',null),
('EL','Evergreen Sekuritas Indonesia','Local',null),
('EP','MNC Sekuritas','Local','MNC Group'),
('ES','Ekokapital Sekuritas','Local',null),
('FO','Forte Global Sekuritas','Local',null),
('FZ','Waterfront Sekuritas Indonesia','Local',null),
('GA','BNC Sekuritas Indonesia','Local',null),
('GR','Panin Sekuritas Tbk','Local','Panin Group'),
('HP','Henan Putihrai Sekuritas','Local',null),
('ID','Anugerah Sekuritas Indonesia','Local',null),
('IF','Samuel Sekuritas Indonesia','Local','Samuel Group'),
('IH','Pacific 2000 Sekuritas','Local',null),
('II','Danatama Makmur Sekuritas','Local',null),
('IN','Investindo Nusantara Sekuritas','Local',null),
('IP','Yugen Bertumbuh Sekuritas','Local',null),
('IT','Inti Teladan Sekuritas','Local',null),
('IU','Indo Capital Sekuritas','Local',null),
('KI','Ciptadana Sekuritas Asia','Local',null),
('LG','Trimegah Sekuritas Indonesia Tbk','Local',null),
('MG','Semesta Indovest Sekuritas','Local',null),
('MI','Victoria Sekuritas Indonesia','Local','Victoria Group'),
('MK','Ekuator Swarna Sekuritas','Local',null),
('MU','Minna Padi Investama Sekuritas','Local',null),
('OK','Net Sekuritas','Local',null),
('PC','FAC Sekuritas Indonesia','Local',null),
('PD','Indo Premier Sekuritas','Local',null),
('PF','Danasakti Sekuritas Indonesia','Local',null),
('PG','Panca Global Sekuritas','Local',null),
('PO','Pilarmas Investindo Sekuritas','Local',null),
('PP','Aldiracita Sekuritas Indonesia','Local',null),
('PS','Paramitra Alfa Sekuritas','Local',null),
('RF','Buana Capital Sekuritas','Local',null),
('RG','Profindo Sekuritas Indonesia','Local',null),
('RO','Nilai Inti Sekuritas','Local',null),
('RS','Yulie Sekuritas Indonesia Tbk','Local',null),
('SA','Elit Sukses Sekuritas','Local',null),
('SC','IMG Sekuritas','Local',null),
('SF','Surya Fajar Sekuritas','Local',null),
('SH','Artha Sekuritas Indonesia','Local',null),
('SQ','BCA Sekuritas','Local',null),
('SS','Supra Sekuritas Indonesia','Local',null),
('TF','Universal Broker Indonesia Sekuritas','Local',null),
('TS','Dwidana Sakti Sekuritas','Local',null),
('XC','Ajaib Sekuritas Asia','Local',null),
('XL','Stockbit Sekuritas Digital','Local',null),
('YB','Jasa Utama Capital Sekuritas','Local',null),
('YJ','Lotus Andalan Sekuritas','Local',null),
('YO','Amantara Sekuritas Indonesia','Local',null),
('ZR','Bumiputera Sekuritas','Local',null)
on conflict (broker_code) do update set
  broker_name = excluded.broker_name,
  investor_type = excluded.investor_type,
  notes = excluded.notes,
  updated_at = now();
