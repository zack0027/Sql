-- Logistic Vanguard - Vistas y Procedimientos
USE logistic_vanguard;

-- Vista: resumen de pedidos
CREATE OR REPLACE VIEW v_pedidos_resumen AS
SELECT
    p.id_pedido,
    p.folio,
    c.nombre        AS cliente,
    p.estatus,
    p.fecha_pedido,
    p.fecha_entrega,
    p.ciudad_entrega,
    COUNT(pd.id_detalle)    AS num_articulos,
    SUM(pd.subtotal)        AS total_calculado
FROM pedidos p
JOIN clientes c        ON c.id_cliente = p.id_cliente
LEFT JOIN pedido_detalle pd ON pd.id_pedido = p.id_pedido
GROUP BY p.id_pedido, p.folio, c.nombre, p.estatus,
         p.fecha_pedido, p.fecha_entrega, p.ciudad_entrega;

-- Vista: nivel de inventario con alertas
CREATE OR REPLACE VIEW v_inventario_alertas AS
SELECT
    pr.codigo,
    pr.nombre       AS producto,
    a.nombre        AS almacen,
    i.cantidad,
    i.stock_minimo,
    i.stock_maximo,
    CASE
        WHEN i.cantidad <= 0              THEN 'SIN STOCK'
        WHEN i.cantidad < i.stock_minimo  THEN 'BAJO MÍNIMO'
        WHEN i.stock_maximo IS NOT NULL
         AND i.cantidad > i.stock_maximo  THEN 'SOBRE MÁXIMO'
        ELSE 'OK'
    END AS alerta
FROM inventario i
JOIN productos pr ON pr.id_producto = i.id_producto
JOIN almacenes a  ON a.id_almacen  = i.id_almacen;

-- Procedimiento: registrar entrada de inventario
DELIMITER $$
CREATE PROCEDURE sp_entrada_inventario(
    IN p_id_producto   INT,
    IN p_id_almacen    INT,
    IN p_cantidad      DECIMAL(12,3),
    IN p_referencia    VARCHAR(50),
    IN p_usuario       VARCHAR(80)
)
BEGIN
    UPDATE inventario
       SET cantidad = cantidad + p_cantidad
     WHERE id_producto = p_id_producto
       AND id_almacen  = p_id_almacen;

    INSERT INTO movimientos_inventario
        (id_producto, id_almacen, tipo, cantidad, referencia, usuario)
    VALUES
        (p_id_producto, p_id_almacen, 'entrada', p_cantidad, p_referencia, p_usuario);
END$$
DELIMITER ;

-- Procedimiento: registrar salida de inventario
DELIMITER $$
CREATE PROCEDURE sp_salida_inventario(
    IN p_id_producto   INT,
    IN p_id_almacen    INT,
    IN p_cantidad      DECIMAL(12,3),
    IN p_referencia    VARCHAR(50),
    IN p_id_pedido     INT,
    IN p_usuario       VARCHAR(80)
)
BEGIN
    DECLARE stock_actual DECIMAL(12,3);

    SELECT cantidad INTO stock_actual
    FROM inventario
    WHERE id_producto = p_id_producto
      AND id_almacen  = p_id_almacen;

    IF stock_actual < p_cantidad THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Stock insuficiente para realizar la salida';
    ELSE
        UPDATE inventario
           SET cantidad = cantidad - p_cantidad
         WHERE id_producto = p_id_producto
           AND id_almacen  = p_id_almacen;

        INSERT INTO movimientos_inventario
            (id_producto, id_almacen, tipo, cantidad, referencia, id_pedido, usuario)
        VALUES
            (p_id_producto, p_id_almacen, 'salida', p_cantidad, p_referencia, p_id_pedido, p_usuario);
    END IF;
END$$
DELIMITER ;

-- Procedimiento: cambiar estatus de pedido
DELIMITER $$
CREATE PROCEDURE sp_actualizar_estatus_pedido(
    IN p_folio   VARCHAR(20),
    IN p_estatus ENUM('pendiente','en_proceso','enviado','entregado','cancelado')
)
BEGIN
    UPDATE pedidos
       SET estatus = p_estatus
     WHERE folio = p_folio;

    IF ROW_COUNT() = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Pedido no encontrado';
    END IF;
END$$
DELIMITER ;
