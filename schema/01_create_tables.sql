-- Logistic Vanguard - Schema Principal
-- Base de datos para gestión logística

CREATE DATABASE IF NOT EXISTS logistic_vanguard;
USE logistic_vanguard;

-- Clientes
CREATE TABLE clientes (
    id_cliente      INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    rfc             VARCHAR(13) UNIQUE,
    correo          VARCHAR(150),
    telefono        VARCHAR(20),
    direccion       VARCHAR(255),
    ciudad          VARCHAR(80),
    pais            VARCHAR(60) DEFAULT 'México',
    fecha_registro  DATETIME DEFAULT CURRENT_TIMESTAMP,
    activo          TINYINT(1) DEFAULT 1
);

-- Proveedores
CREATE TABLE proveedores (
    id_proveedor    INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    rfc             VARCHAR(13) UNIQUE,
    correo          VARCHAR(150),
    telefono        VARCHAR(20),
    direccion       VARCHAR(255),
    ciudad          VARCHAR(80),
    pais            VARCHAR(60) DEFAULT 'México',
    fecha_registro  DATETIME DEFAULT CURRENT_TIMESTAMP,
    activo          TINYINT(1) DEFAULT 1
);

-- Almacenes / Bodegas
CREATE TABLE almacenes (
    id_almacen      INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    ubicacion       VARCHAR(255),
    ciudad          VARCHAR(80),
    capacidad_m3    DECIMAL(10,2),
    responsable     VARCHAR(100),
    activo          TINYINT(1) DEFAULT 1
);

-- Productos
CREATE TABLE productos (
    id_producto     INT AUTO_INCREMENT PRIMARY KEY,
    codigo          VARCHAR(50) UNIQUE NOT NULL,
    nombre          VARCHAR(150) NOT NULL,
    descripcion     TEXT,
    unidad_medida   VARCHAR(20) DEFAULT 'pieza',
    peso_kg         DECIMAL(10,3),
    volumen_m3      DECIMAL(10,4),
    precio_unitario DECIMAL(12,2),
    id_proveedor    INT,
    activo          TINYINT(1) DEFAULT 1,
    FOREIGN KEY (id_proveedor) REFERENCES proveedores(id_proveedor)
);

-- Inventario por almacén
CREATE TABLE inventario (
    id_inventario   INT AUTO_INCREMENT PRIMARY KEY,
    id_producto     INT NOT NULL,
    id_almacen      INT NOT NULL,
    cantidad        DECIMAL(12,3) DEFAULT 0,
    stock_minimo    DECIMAL(12,3) DEFAULT 0,
    stock_maximo    DECIMAL(12,3),
    ultima_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (id_producto) REFERENCES productos(id_producto),
    FOREIGN KEY (id_almacen) REFERENCES almacenes(id_almacen),
    UNIQUE KEY uq_producto_almacen (id_producto, id_almacen)
);

-- Conductores / Transportistas
CREATE TABLE conductores (
    id_conductor    INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    licencia        VARCHAR(30) UNIQUE,
    tipo_licencia   VARCHAR(10),
    telefono        VARCHAR(20),
    correo          VARCHAR(150),
    fecha_contrato  DATE,
    activo          TINYINT(1) DEFAULT 1
);

-- Vehículos
CREATE TABLE vehiculos (
    id_vehiculo     INT AUTO_INCREMENT PRIMARY KEY,
    placa           VARCHAR(15) UNIQUE NOT NULL,
    tipo            ENUM('camion','camioneta','trailer','furgon') NOT NULL,
    marca           VARCHAR(60),
    modelo          VARCHAR(60),
    año             YEAR,
    capacidad_kg    DECIMAL(10,2),
    capacidad_m3    DECIMAL(10,2),
    id_conductor    INT,
    activo          TINYINT(1) DEFAULT 1,
    FOREIGN KEY (id_conductor) REFERENCES conductores(id_conductor)
);

-- Pedidos
CREATE TABLE pedidos (
    id_pedido       INT AUTO_INCREMENT PRIMARY KEY,
    folio           VARCHAR(20) UNIQUE NOT NULL,
    id_cliente      INT NOT NULL,
    fecha_pedido    DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_entrega   DATETIME,
    estatus         ENUM('pendiente','en_proceso','enviado','entregado','cancelado') DEFAULT 'pendiente',
    direccion_entrega VARCHAR(255),
    ciudad_entrega  VARCHAR(80),
    notas           TEXT,
    total           DECIMAL(14,2),
    FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente)
);

-- Detalle de pedidos
CREATE TABLE pedido_detalle (
    id_detalle      INT AUTO_INCREMENT PRIMARY KEY,
    id_pedido       INT NOT NULL,
    id_producto     INT NOT NULL,
    cantidad        DECIMAL(12,3) NOT NULL,
    precio_unitario DECIMAL(12,2) NOT NULL,
    subtotal        DECIMAL(14,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    id_almacen_origen INT,
    FOREIGN KEY (id_pedido) REFERENCES pedidos(id_pedido),
    FOREIGN KEY (id_producto) REFERENCES productos(id_producto),
    FOREIGN KEY (id_almacen_origen) REFERENCES almacenes(id_almacen)
);

-- Rutas de entrega
CREATE TABLE rutas (
    id_ruta         INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100),
    origen          VARCHAR(150),
    destino         VARCHAR(150),
    distancia_km    DECIMAL(10,2),
    tiempo_estimado_hrs DECIMAL(5,2),
    activo          TINYINT(1) DEFAULT 1
);

-- Envíos
CREATE TABLE envios (
    id_envio        INT AUTO_INCREMENT PRIMARY KEY,
    folio_envio     VARCHAR(20) UNIQUE NOT NULL,
    id_pedido       INT NOT NULL,
    id_vehiculo     INT,
    id_conductor    INT,
    id_ruta         INT,
    fecha_salida    DATETIME,
    fecha_llegada   DATETIME,
    estatus         ENUM('programado','en_transito','entregado','fallido') DEFAULT 'programado',
    observaciones   TEXT,
    FOREIGN KEY (id_pedido) REFERENCES pedidos(id_pedido),
    FOREIGN KEY (id_vehiculo) REFERENCES vehiculos(id_vehiculo),
    FOREIGN KEY (id_conductor) REFERENCES conductores(id_conductor),
    FOREIGN KEY (id_ruta) REFERENCES rutas(id_ruta)
);

-- Movimientos de inventario (entradas/salidas)
CREATE TABLE movimientos_inventario (
    id_movimiento   INT AUTO_INCREMENT PRIMARY KEY,
    id_producto     INT NOT NULL,
    id_almacen      INT NOT NULL,
    tipo            ENUM('entrada','salida','ajuste','transferencia') NOT NULL,
    cantidad        DECIMAL(12,3) NOT NULL,
    referencia      VARCHAR(50),
    id_pedido       INT,
    fecha           DATETIME DEFAULT CURRENT_TIMESTAMP,
    usuario         VARCHAR(80),
    notas           TEXT,
    FOREIGN KEY (id_producto) REFERENCES productos(id_producto),
    FOREIGN KEY (id_almacen) REFERENCES almacenes(id_almacen),
    FOREIGN KEY (id_pedido) REFERENCES pedidos(id_pedido)
);
