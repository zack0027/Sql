-- Logistic Vanguard - Consultas principales
USE logistic_vanguard;

-- 1. Pedidos con estatus y cliente
SELECT
    p.folio,
    c.nombre        AS cliente,
    p.fecha_pedido,
    p.fecha_entrega,
    p.estatus,
    p.ciudad_entrega,
    p.total
FROM pedidos p
JOIN clientes c ON c.id_cliente = p.id_cliente
ORDER BY p.fecha_pedido DESC;

-- 2. Inventario bajo stock mínimo
SELECT
    pr.codigo,
    pr.nombre               AS producto,
    a.nombre                AS almacen,
    i.cantidad,
    i.stock_minimo,
    (i.stock_minimo - i.cantidad) AS faltante
FROM inventario i
JOIN productos pr ON pr.id_producto = i.id_producto
JOIN almacenes a  ON a.id_almacen  = i.id_almacen
WHERE i.cantidad < i.stock_minimo
ORDER BY faltante DESC;

-- 3. Envíos en tránsito con conductor y vehículo
SELECT
    e.folio_envio,
    p.folio         AS pedido,
    c.nombre        AS cliente,
    co.nombre       AS conductor,
    v.placa,
    v.tipo,
    r.nombre        AS ruta,
    e.fecha_salida,
    r.tiempo_estimado_hrs,
    e.estatus
FROM envios e
JOIN pedidos p   ON p.id_pedido    = e.id_pedido
JOIN clientes c  ON c.id_cliente   = p.id_cliente
LEFT JOIN conductores co ON co.id_conductor = e.id_conductor
LEFT JOIN vehiculos v    ON v.id_vehiculo   = e.id_vehiculo
LEFT JOIN rutas r        ON r.id_ruta       = e.id_ruta
WHERE e.estatus = 'en_transito';

-- 4. Resumen de ventas por cliente
SELECT
    c.nombre                        AS cliente,
    COUNT(p.id_pedido)              AS total_pedidos,
    SUM(p.total)                    AS monto_total,
    AVG(p.total)                    AS ticket_promedio,
    MAX(p.fecha_pedido)             AS ultimo_pedido
FROM pedidos p
JOIN clientes c ON c.id_cliente = p.id_cliente
WHERE p.estatus != 'cancelado'
GROUP BY c.id_cliente, c.nombre
ORDER BY monto_total DESC;

-- 5. Productos más vendidos (por cantidad en pedidos)
SELECT
    pr.codigo,
    pr.nombre                       AS producto,
    SUM(pd.cantidad)                AS cantidad_vendida,
    SUM(pd.subtotal)                AS ingresos
FROM pedido_detalle pd
JOIN productos pr ON pr.id_producto = pd.id_producto
JOIN pedidos p    ON p.id_pedido    = pd.id_pedido
WHERE p.estatus != 'cancelado'
GROUP BY pr.id_producto, pr.codigo, pr.nombre
ORDER BY cantidad_vendida DESC;

-- 6. Movimientos de inventario del mes actual
SELECT
    DATE(m.fecha)       AS fecha,
    pr.nombre           AS producto,
    a.nombre            AS almacen,
    m.tipo,
    m.cantidad,
    m.referencia,
    m.usuario
FROM movimientos_inventario m
JOIN productos pr ON pr.id_producto = m.id_producto
JOIN almacenes a  ON a.id_almacen  = m.id_almacen
WHERE MONTH(m.fecha) = MONTH(CURRENT_DATE())
  AND YEAR(m.fecha)  = YEAR(CURRENT_DATE())
ORDER BY m.fecha DESC;

-- 7. Disponibilidad de vehículos
SELECT
    v.placa,
    v.tipo,
    v.marca,
    v.modelo,
    v.capacidad_kg,
    co.nombre       AS conductor,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM envios e
            WHERE e.id_vehiculo = v.id_vehiculo
              AND e.estatus = 'en_transito'
        ) THEN 'En ruta'
        ELSE 'Disponible'
    END AS disponibilidad
FROM vehiculos v
LEFT JOIN conductores co ON co.id_conductor = v.id_conductor
WHERE v.activo = 1;

-- 8. Valor total del inventario por almacén
SELECT
    a.nombre                        AS almacen,
    COUNT(DISTINCT i.id_producto)   AS num_productos,
    SUM(i.cantidad * pr.precio_unitario) AS valor_inventario
FROM inventario i
JOIN almacenes a  ON a.id_almacen  = i.id_almacen
JOIN productos pr ON pr.id_producto = i.id_producto
GROUP BY a.id_almacen, a.nombre
ORDER BY valor_inventario DESC;
