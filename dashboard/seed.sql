-- Spice Garden — sample data. Safe to re-run (clears and reloads).
TRUNCATE bookings, restaurant_tables, menu_items RESTART IDENTITY CASCADE;

-- ---- Menu (a couple are marked unavailable to demo the toggle) ----
INSERT INTO menu_items (name, category, description, price, is_available) VALUES
('Paneer Tikka',          'Starters', 'Char-grilled cottage cheese with spices',          280, TRUE),
('Chicken 65',            'Starters', 'Spicy deep-fried chicken, South-Indian style',     320, FALSE),
('Veg Manchurian',        'Starters', 'Veg balls in Indo-Chinese sauce',                  260, TRUE),
('Gobi Manchurian',       'Starters', 'Crispy cauliflower in chilli-garlic sauce',        240, TRUE),
('Butter Chicken',        'Mains',    'Tandoori chicken in creamy tomato gravy',          420, TRUE),
('Rogan Josh',            'Mains',    'Slow-cooked lamb curry with Kashmiri spices',      480, TRUE),
('Dal Makhani',           'Mains',    'Black lentils simmered overnight with butter',     320, TRUE),
('Paneer Butter Masala',  'Mains',    'Cottage cheese in rich tomato-cashew gravy',       360, TRUE),
('Chicken Biryani',       'Mains',    'Fragrant basmati rice cooked with chicken',        380, TRUE),
('Veg Hakka Noodles',     'Mains',    'Stir-fried noodles with vegetables',               280, TRUE),
('Chilli Chicken',        'Mains',    'Indo-Chinese chicken in a spicy sauce',            340, TRUE),
('Butter Naan',           'Breads',   'Soft leavened bread brushed with butter',           60, TRUE),
('Garlic Naan',           'Breads',   'Naan topped with garlic and coriander',             80, TRUE),
('Tandoori Roti',         'Breads',   'Whole-wheat clay-oven bread',                       40, TRUE),
('Gulab Jamun',           'Desserts', 'Fried milk dumplings in sugar syrup',              120, TRUE),
('Gajar Halwa',           'Desserts', 'Carrot pudding with nuts (seasonal)',              140, FALSE),
('Masala Chai',           'Drinks',   'Spiced Indian tea',                                 60, TRUE),
('Sweet Lassi',           'Drinks',   'Chilled sweet yoghurt drink',                      100, TRUE);

-- ---- Tables (mix of available + allocated) ----
INSERT INTO restaurant_tables (table_number, capacity, location, status) VALUES
(1,  2,  'Window',  'available'),
(2,  2,  'Indoor',  'available'),
(3,  4,  'Indoor',  'available'),
(4,  4,  'Indoor',  'allocated'),
(5,  4,  'Patio',   'available'),
(6,  6,  'Indoor',  'available'),
(7,  6,  'Patio',   'allocated'),
(8,  8,  'Indoor',  'available'),
(9,  10, 'Banquet', 'available'),
(10, 12, 'Banquet', 'allocated');

-- ---- Existing bookings (5 confirmed + 1 cancelled) ----
INSERT INTO bookings (customer_name, party_size, booking_date, booking_time, table_id, special_requests, status) VALUES
('Aarav Sharma', 4,  DATE '2026-06-21', TIME '19:30', 4,  'Window seat if possible', 'confirmed'),
('Priya Nair',   6,  DATE '2026-06-21', TIME '20:00', 7,  'Birthday - bringing a cake', 'confirmed'),
('Rahul Verma',  2,  DATE '2026-06-22', TIME '13:00', 1,  NULL, 'confirmed'),
('Sneha Reddy',  12, DATE '2026-06-21', TIME '21:00', 10, 'Corporate dinner', 'confirmed'),
('Imran Khan',   8,  DATE '2026-06-23', TIME '19:00', 8,  'Need a high chair', 'confirmed'),
('Meera Iyer',   4,  DATE '2026-06-24', TIME '20:30', 3,  NULL, 'cancelled');
