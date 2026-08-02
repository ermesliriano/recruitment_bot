# Reprocesado de las candidaturas completadas

El comando usa una candidatura de referencia para limitar el lote al mismo
**tenant** y la misma **vacante**. Solo selecciona filas con `score_total IS NOT
NULL`, que es la definición utilizada por el ranking para una candidatura
completada. Las candidaturas incompletas se muestran como excluidas y no se
modifican.

Candidatura de referencia del caso observado:

```text
ec9052bf-adf9-4c46-a891-fca0fd1c30a8
```

## 1. Desplegar primero el cambio

El reprocesado debe ejecutarse después de desplegar el extractor por página y el
prompt actualizado. De lo contrario se repetiría el análisis antiguo.

## 2. Ejecutar el dry-run

Desde una Shell de Render o desde un entorno con `DATABASE_URL` y
`OPENAI_API_KEY` configurados:

```bash
python scripts/reprocess_completed_cv_evaluations.py \
  --reference-application-id ec9052bf-adf9-4c46-a891-fca0fd1c30a8 \
  --expected-count 7
```

El resultado esperado es:

```text
Candidaturas completadas seleccionadas: 7
Candidaturas incompletas excluidas automáticamente: 1
Dry-run completado.
```

No continúes si el número de completadas no es exactamente 7. El guard de
`--expected-count` aborta sin escribir cuando el número difiere.

## 3. Aplicar el reprocesado

```bash
python scripts/reprocess_completed_cv_evaluations.py \
  --reference-application-id ec9052bf-adf9-4c46-a891-fca0fd1c30a8 \
  --expected-count 7 \
  --apply
```

Para cada candidatura completada el script:

1. vuelve a extraer todas las páginas del PDF;
2. aplica OCR solo a las páginas sin texto suficiente;
3. vuelve a ejecutar la evaluación LLM con el expediente completo;
4. sustituye únicamente respuestas prellenadas anteriormente por el LLM;
5. conserva respuestas introducidas por el candidato;
6. recalcula puntuación y clasificación;
7. no modifica la conversación ni envía mensajes al candidato.

El proceso es reejecutable. Si una candidatura falla, se revierte solamente esa
candidatura y el comando termina con código distinto de cero.
