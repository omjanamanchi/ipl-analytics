-- =====================================================================
-- Reference data that is NOT in Cricsheet: roles, franchises, name history,
-- season auction rules, awards, demo scouts.
-- Venues are loaded from data/venue_aliases.csv by etl/load_cricsheet.py
-- BEFORE this file runs (franchise.home_venue_id looks venues up by name).
-- =====================================================================

INSERT INTO role (role_code, description, sort_order) VALUES
  ('BAT',  'Batter',              1),
  ('WK',   'Wicketkeeper-Batter', 2),
  ('AR',   'All-rounder',         3),
  ('BOWL', 'Bowler',              4);

-- Owner groups as of the 2026 season. RCB was bought by an Aditya Birla Group-led
-- consortium in 2026. Re-check owners on iplt20.com before your demo.
INSERT INTO franchise (short_code, current_name, city, owner_group, home_venue_id, founded_season, is_active)
SELECT v.short_code, v.current_name, v.city, v.owner_group,
       (SELECT venue_id FROM venue WHERE name = v.home_venue), v.founded, v.active
FROM (VALUES
  ('CSK',  'Chennai Super Kings',         'Chennai',    'Chennai Super Kings Cricket Ltd (India Cements)', 'MA Chidambaram Stadium',                                   2008, TRUE),
  ('MI',   'Mumbai Indians',              'Mumbai',     'Reliance Industries (Indiawin Sports)',          'Wankhede Stadium',                                         2008, TRUE),
  ('RCB',  'Royal Challengers Bengaluru', 'Bengaluru',  'Aditya Birla Group-led consortium',              'M Chinnaswamy Stadium',                                    2008, TRUE),
  ('KKR',  'Kolkata Knight Riders',       'Kolkata',    'Knight Riders Group (Red Chillies Entertainment, Mehta Group)', 'Eden Gardens',                     2008, TRUE),
  ('DC',   'Delhi Capitals',              'Delhi',      'GMR Group & JSW Group',                          'Arun Jaitley Stadium',                                     2008, TRUE),
  ('PBKS', 'Punjab Kings',                'Mohali',     'KPH Dream Cricket (Burman, Wadia, Zinta, Paul)', 'Maharaja Yadavindra Singh International Cricket Stadium', 2008, TRUE),
  ('RR',   'Rajasthan Royals',            'Jaipur',     'Royal Multisport (Manoj Badale)',                'Sawai Mansingh Stadium',                                   2008, TRUE),
  ('SRH',  'Sunrisers Hyderabad',         'Hyderabad',  'Sun TV Network',                                 'Rajiv Gandhi International Stadium',                       2013, TRUE),
  ('LSG',  'Lucknow Super Giants',        'Lucknow',    'RPSG Group',                                     'Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium', 2022, TRUE),
  ('GT',   'Gujarat Titans',              'Ahmedabad',  'Torrent Group & CVC Capital',                    'Narendra Modi Stadium',                                    2022, TRUE),
  ('DCH',  'Deccan Chargers',             'Hyderabad',  'Deccan Chronicle Holdings',                      'Rajiv Gandhi International Stadium',                       2008, FALSE),
  ('KTK',  'Kochi Tuskers Kerala',        'Kochi',      'Rendezvous Sports World',                        'Nehru Stadium',                                            2011, FALSE),
  ('PWI',  'Pune Warriors',               'Pune',       'Sahara Adventure Sports',                        'Maharashtra Cricket Association Stadium',                  2011, FALSE),
  ('RPS',  'Rising Pune Supergiant',      'Pune',       'RPSG Group',                                     'Maharashtra Cricket Association Stadium',                  2016, FALSE),
  ('GL',   'Gujarat Lions',               'Rajkot',     'Intex Technologies',                             'Saurashtra Cricket Association Stadium',                   2016, FALSE)
) AS v(short_code, current_name, city, owner_group, home_venue, founded, active);

-- Every spelling Cricsheet uses for a team -> franchise.
INSERT INTO franchise_name (name, franchise_id, from_season, to_season)
SELECT v.name, f.franchise_id, v.from_s, v.to_s
FROM (VALUES
  ('Chennai Super Kings',          'CSK',  2008, NULL),
  ('Mumbai Indians',               'MI',   2008, NULL),
  ('Royal Challengers Bangalore',  'RCB',  2008, 2023),
  ('Royal Challengers Bengaluru',  'RCB',  2024, NULL),
  ('Kolkata Knight Riders',        'KKR',  2008, NULL),
  ('Delhi Daredevils',             'DC',   2008, 2018),
  ('Delhi Capitals',               'DC',   2019, NULL),
  ('Kings XI Punjab',              'PBKS', 2008, 2020),
  ('Punjab Kings',                 'PBKS', 2021, NULL),
  ('Rajasthan Royals',             'RR',   2008, NULL),
  ('Sunrisers Hyderabad',          'SRH',  2013, NULL),
  ('Lucknow Super Giants',         'LSG',  2022, NULL),
  ('Gujarat Titans',               'GT',   2022, NULL),
  ('Deccan Chargers',              'DCH',  2008, 2012),
  ('Kochi Tuskers Kerala',         'KTK',  2011, 2011),
  ('Pune Warriors',                'PWI',  2011, 2013),
  ('Rising Pune Supergiants',      'RPS',  2016, 2016),
  ('Rising Pune Supergiant',       'RPS',  2017, 2017),
  ('Gujarat Lions',                'GL',   2016, 2017)
) AS v(name, code, from_s, to_s)
JOIN franchise f ON f.short_code = v.code;

-- Seasons 2008-2027. Dates, champion and runner-up are filled by the loader from match data.
-- Auction rules: 2025 mega auction (Rs 120 cr purse) and 2026 mini auction (Rs 125 cr,
-- overseas fee capped at Rs 18 cr). 2027 assumes the 2026 rules until the BCCI announces new ones.
INSERT INTO season (season_year) SELECT generate_series(2008, 2027);
UPDATE season SET purse_cr = 120, min_squad = 18, max_squad = 25, max_overseas = 8 WHERE season_year = 2025;
UPDATE season SET purse_cr = 125, min_squad = 18, max_squad = 25, max_overseas = 8, overseas_cap_cr = 18
 WHERE season_year IN (2026, 2027);

INSERT INTO award (award_name, description) VALUES
  ('Orange Cap',            'Most runs in the season'),
  ('Purple Cap',            'Most wickets in the season'),
  ('Most Valuable Player',  'Most IPL MVP points: 3.5/six, 2.5/four, 3.5/wicket, 1/dot ball, 2.5/catch or stumping'),
  ('Most Sixes',            'Most sixes in the season');

-- password_hash is set by etl/load_cricsheet.py after insert (werkzeug.security)
INSERT INTO scout (username, display_name) VALUES
  ('om',     'Om Janamanchi'),
  ('scout2', 'Assistant Scout');
