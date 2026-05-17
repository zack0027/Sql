# Logistic Vanguard - Base de Datos SQL

Sistema de gestión logística completo: inventario, pedidos, envíos y transporte.

## Estructura del proyecto

```
Sql/
├── schema/
│   ├── 01_create_tables.sql        # Creación de tablas
│   └── 04_views_procedures.sql     # Vistas y procedimientos almacenados
├── data/
│   └── 02_insert_data.sql          # Datos iniciales de prueba
├── queries/
│   └── 03_consultas.sql            # Consultas frecuentes
└── docs/
    └── README.md
```

## Módulos del sistema

| Módulo        | Tablas principales                              |
|---------------|-------------------------------------------------|
| Clientes      | `clientes`                                      |
| Proveedores   | `proveedores`                                   |
| Almacenes     | `almacenes`, `inventario`, `movimientos_inventario` |
| Productos     | `productos`                                     |
| Pedidos       | `pedidos`, `pedido_detalle`                     |
| Transporte    | `conductores`, `vehiculos`, `rutas`, `envios`   |

## Instalación

```bash
# 1. Crear base de datos y tablas
mysql -u root -p < schema/01_create_tables.sql

# 2. Insertar datos de prueba
mysql -u root -p logistic_vanguard < data/02_insert_data.sql

# 3. Crear vistas y procedimientos
mysql -u root -p logistic_vanguard < schema/04_views_procedures.sql

# 4. Ejecutar consultas de ejemplo
mysql -u root -p logistic_vanguard < queries/03_consultas.sql
```

## Procedimientos almacenados

```sql
-- Entrada de mercancía al inventario
CALL sp_entrada_inventario(1, 1, 500, 'COMPRA-003', 'usuario');

-- Salida de mercancía del inventario
CALL sp_salida_inventario(1, 1, 100, 'PED-2024-005', 5, 'usuario');

-- Actualizar estatus de pedido
CALL sp_actualizar_estatus_pedido('PED-2024-003', 'enviado');
```

## Vistas disponibles

```sql
SELECT * FROM v_pedidos_resumen;
SELECT * FROM v_inventario_alertas WHERE alerta != 'OK';
```
