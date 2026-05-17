-- Logistic Vanguard - Datos de prueba
USE logistic_vanguard;

-- Almacenes
INSERT INTO almacenes (nombre, ubicacion, ciudad, capacidad_m3, responsable) VALUES
('Almacén Central',  'Av. Industrial 100', 'Ciudad de México', 5000.00, 'Carlos Mendoza'),
('Bodega Norte',     'Blvd. Logístico 45',  'Monterrey',        3200.00, 'Ana Rodríguez'),
('Depósito Occidente','Carr. Guadalajara Km 12','Guadalajara',  2800.00, 'Luis Torres');

-- Clientes
INSERT INTO clientes (nombre, rfc, correo, telefono, direccion, ciudad) VALUES
('Distribuidora Alfa SA',    'DAL010101AAA', 'contacto@alfa.mx',    '5512345678', 'Av. Reforma 200',   'Ciudad de México'),
('Comercial Beta',           'CBE020202BBB', 'ventas@beta.mx',      '8112345678', 'Calz. Independencia','Monterrey'),
('Logística Gamma Corp',     'LGC030303CCC', 'ops@gamma.mx',        '3312345678', 'Av. Vallarta 500',  'Guadalajara'),
('Transportes Delta',        'TDE040404DDD', 'admin@delta.mx',      '5598765432', 'Blvd. Tlalpan 300', 'Ciudad de México');

-- Proveedores
INSERT INTO proveedores (nombre, rfc, correo, telefono, direccion, ciudad) VALUES
('Proveedor Nacional MX',  'PNM050505EEE', 'compras@pnm.mx',  '5511112222', 'Zona Industrial 5', 'Querétaro'),
('Importadora Global SA',  'IGS060606FFF', 'import@global.mx','8133334444', 'Puerto Industrial 1','Veracruz'),
('Insumos Express',        'IEX070707GGG', 'info@insumos.mx', '3355556666', 'Parque Logístico 8', 'Guadalajara');

-- Conductores
INSERT INTO conductores (nombre, licencia, tipo_licencia, telefono, fecha_contrato) VALUES
('Jorge Herrera López',   'LIC-001-MX', 'E',  '5511223344', '2022-01-15'),
('María Sánchez Ruiz',    'LIC-002-MX', 'C',  '8122334455', '2021-06-01'),
('Roberto Díaz García',   'LIC-003-MX', 'E',  '3333445566', '2023-03-10'),
('Patricia Luna Torres',  'LIC-004-MX', 'C',  '5544556677', '2022-09-20');

-- Vehículos
INSERT INTO vehiculos (placa, tipo, marca, modelo, año, capacidad_kg, capacidad_m3, id_conductor) VALUES
('ABC-123-MX', 'trailer',   'Kenworth', 'T680',  2021, 25000.00, 85.00, 1),
('DEF-456-MX', 'camion',    'Freightliner','M2', 2020, 10000.00, 42.00, 2),
('GHI-789-MX', 'camioneta', 'Ford',     'F-350', 2022,  3500.00, 10.00, 3),
('JKL-012-MX', 'furgon',    'Mercedes', 'Sprinter',2023, 1500.00,  8.00, 4);

-- Productos
INSERT INTO productos (codigo, nombre, descripcion, unidad_medida, peso_kg, volumen_m3, precio_unitario, id_proveedor) VALUES
('PROD-001', 'Caja de Cartón Grande',  'Caja corrugada 60x40x40 cm',    'pieza',  0.500, 0.096,  35.00, 1),
('PROD-002', 'Palet de Madera',        'Palet estándar 120x80 cm',       'pieza', 22.000, 0.096, 320.00, 1),
('PROD-003', 'Film Stretch 500m',      'Rollo polietileno para embalaje','rollo',  2.800, 0.014, 280.00, 2),
('PROD-004', 'Cinta Adhesiva Industrial','Cinta de 50mm x 100m',         'rollo',  0.350, 0.001,  45.00, 3),
('PROD-005', 'Etiqueta Térmica 10x15', 'Etiquetas para impresora Zebra', 'caja',   1.200, 0.002, 180.00, 3);

-- Inventario inicial
INSERT INTO inventario (id_producto, id_almacen, cantidad, stock_minimo, stock_maximo) VALUES
(1, 1, 2500, 500, 5000),
(1, 2,  800, 200, 2000),
(2, 1,  350,  50,  800),
(2, 3,  120,  30,  400),
(3, 1,  200,  50,  600),
(4, 1, 1500, 300, 3000),
(4, 2,  600, 100, 1500),
(5, 1,  900, 200, 2000);

-- Rutas
INSERT INTO rutas (nombre, origen, destino, distancia_km, tiempo_estimado_hrs) VALUES
('CDMX - Monterrey',    'Ciudad de México', 'Monterrey',    906.00, 10.50),
('CDMX - Guadalajara',  'Ciudad de México', 'Guadalajara',  544.00,  6.00),
('Monterrey - Guadalajara','Monterrey',    'Guadalajara',  725.00,  8.00),
('CDMX - Querétaro',    'Ciudad de México', 'Querétaro',    220.00,  2.50);

-- Pedidos
INSERT INTO pedidos (folio, id_cliente, fecha_entrega, estatus, direccion_entrega, ciudad_entrega, total) VALUES
('PED-2024-001', 1, '2024-02-15 10:00:00', 'entregado',  'Av. Reforma 200',    'Ciudad de México', 12500.00),
('PED-2024-002', 2, '2024-02-20 14:00:00', 'enviado',    'Calz. Independencia','Monterrey',         8750.00),
('PED-2024-003', 3, '2024-03-01 09:00:00', 'en_proceso', 'Av. Vallarta 500',   'Guadalajara',       5400.00),
('PED-2024-004', 4, '2024-03-05 16:00:00', 'pendiente',  'Blvd. Tlalpan 300',  'Ciudad de México',  3200.00);

-- Detalle pedidos
INSERT INTO pedido_detalle (id_pedido, id_producto, cantidad, precio_unitario, id_almacen_origen) VALUES
(1, 1, 200, 35.00, 1),
(1, 3,  15, 280.00, 1),
(2, 2,  20, 320.00, 1),
(2, 4,  50,  45.00, 2),
(3, 1, 100, 35.00, 2),
(3, 5,  10, 180.00, 1),
(4, 4, 200, 45.00, 1),
(4, 5,  40, 180.00, 1);

-- Envíos
INSERT INTO envios (folio_envio, id_pedido, id_vehiculo, id_conductor, id_ruta, fecha_salida, fecha_llegada, estatus) VALUES
('ENV-2024-001', 1, 2, 2, 4, '2024-02-14 08:00:00', '2024-02-15 09:30:00', 'entregado'),
('ENV-2024-002', 2, 1, 1, 1, '2024-02-19 07:00:00', NULL,                  'en_transito'),
('ENV-2024-003', 3, 3, 3, 2, '2024-02-28 09:00:00', NULL,                  'programado');

-- Movimientos de inventario
INSERT INTO movimientos_inventario (id_producto, id_almacen, tipo, cantidad, referencia, id_pedido, usuario) VALUES
(1, 1, 'salida', 200, 'PED-2024-001', 1, 'sistema'),
(3, 1, 'salida',  15, 'PED-2024-001', 1, 'sistema'),
(2, 1, 'salida',  20, 'PED-2024-002', 2, 'sistema'),
(4, 2, 'salida',  50, 'PED-2024-002', 2, 'sistema'),
(1, 1, 'entrada',500, 'COMPRA-001',  NULL,'admin'),
(2, 1, 'entrada', 80, 'COMPRA-002',  NULL,'admin');
