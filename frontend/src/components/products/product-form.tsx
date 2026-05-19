import * as React from "react"

import { FormField } from "@/components/common/form-field"
import { InlineAlert } from "@/components/common/inline-alert"
import { Button } from "@/components/ui/button"
import type { ProductInput } from "@/types/product"
import { formatPercent } from "@/utils/formatters"

export type ProductFormValues = {
  title: string
  costPrice: string
  sellingPrice: string
  stockQuantity: string
  supplierLeadTime: string
  minimumMargin: string
}

type ProductFormProps = {
  onSubmit: (input: ProductInput) => Promise<void>
  isSubmitting?: boolean
  successMessage?: string | null
  errorMessage?: string | null
  submitLabel?: string
}

const initialValues: ProductFormValues = {
  title: "",
  costPrice: "",
  sellingPrice: "",
  stockQuantity: "",
  supplierLeadTime: "",
  minimumMargin: "",
}

type FieldErrors = Partial<Record<keyof ProductFormValues, string>>

function parseNumber(value: string) {
  if (!value) {
    return NaN
  }

  return Number(value)
}

export function ProductForm({
  onSubmit,
  isSubmitting = false,
  successMessage,
  errorMessage,
  submitLabel = "Save product",
}: ProductFormProps) {
  const [values, setValues] = React.useState<ProductFormValues>(initialValues)
  const [errors, setErrors] = React.useState<FieldErrors>({})

  const actualMargin = React.useMemo(() => {
    const cost = parseNumber(values.costPrice)
    const selling = parseNumber(values.sellingPrice)

    if (!Number.isFinite(cost) || !Number.isFinite(selling) || selling <= 0) {
      return null
    }

    return ((selling - cost) / selling) * 100
  }, [values.costPrice, values.sellingPrice])

  const validate = (formValues: ProductFormValues) => {
    const nextErrors: FieldErrors = {}

    if (!formValues.title.trim()) {
      nextErrors.title = "Product title is required."
    }

    const cost = parseNumber(formValues.costPrice)
    if (!Number.isFinite(cost) || cost <= 0) {
      nextErrors.costPrice = "Cost price must be greater than 0."
    }

    const selling = parseNumber(formValues.sellingPrice)
    if (!Number.isFinite(selling) || selling <= 0) {
      nextErrors.sellingPrice = "Selling price must be greater than 0."
    }

    if (Number.isFinite(cost) && Number.isFinite(selling) && selling < cost) {
      nextErrors.sellingPrice = "Selling price should be higher than cost."
    }

    const stock = parseNumber(formValues.stockQuantity)
    if (!Number.isFinite(stock) || stock < 0) {
      nextErrors.stockQuantity = "Stock quantity must be 0 or higher."
    }

    const leadTime = parseNumber(formValues.supplierLeadTime)
    if (!Number.isFinite(leadTime) || leadTime < 0) {
      nextErrors.supplierLeadTime = "Lead time must be 0 or higher."
    }

    const minimumMargin = parseNumber(formValues.minimumMargin)
    if (!Number.isFinite(minimumMargin) || minimumMargin < 0) {
      nextErrors.minimumMargin = "Minimum margin must be 0% or higher."
    }

    return nextErrors
  }

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target
    setValues((prev) => ({ ...prev, [name]: value }))
    setErrors((prev) => ({ ...prev, [name]: undefined }))
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const validationErrors = validate(values)
    setErrors(validationErrors)

    if (Object.keys(validationErrors).length > 0) {
      return
    }

    const input: ProductInput = {
      title: values.title.trim(),
      costPrice: parseNumber(values.costPrice),
      sellingPrice: parseNumber(values.sellingPrice),
      stockQuantity: parseNumber(values.stockQuantity),
      supplierLeadTime: parseNumber(values.supplierLeadTime),
      minimumMargin: parseNumber(values.minimumMargin),
    }

    await onSubmit(input)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {successMessage ? (
        <InlineAlert variant="success" message={successMessage} />
      ) : null}
      {errorMessage ? (
        <InlineAlert variant="error" message={errorMessage} />
      ) : null}

      <fieldset className="space-y-4" disabled={isSubmitting}>
        <FormField
          id="product-title"
          name="title"
          label="Product title"
          value={values.title}
          placeholder="Premium denim jacket"
          onChange={handleChange}
          error={errors.title}
        />

        <div className="grid gap-4 md:grid-cols-2">
          <FormField
            id="product-cost"
            name="costPrice"
            label="Cost price (BDT)"
            type="number"
            inputMode="decimal"
            min={0}
            step={0.01}
            value={values.costPrice}
            placeholder="1200"
            onChange={handleChange}
            error={errors.costPrice}
          />
          <FormField
            id="product-selling"
            name="sellingPrice"
            label="Selling price (BDT)"
            type="number"
            inputMode="decimal"
            min={0}
            step={0.01}
            value={values.sellingPrice}
            placeholder="1790"
            onChange={handleChange}
            error={errors.sellingPrice}
            helperText={
              actualMargin !== null
                ? `Projected margin ${formatPercent(actualMargin)}`
                : undefined
            }
          />
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <FormField
            id="product-stock"
            name="stockQuantity"
            label="Stock quantity"
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={values.stockQuantity}
            placeholder="150"
            onChange={handleChange}
            error={errors.stockQuantity}
          />
          <FormField
            id="product-lead-time"
            name="supplierLeadTime"
            label="Supplier lead time (days)"
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={values.supplierLeadTime}
            placeholder="7"
            onChange={handleChange}
            error={errors.supplierLeadTime}
          />
          <FormField
            id="product-margin"
            name="minimumMargin"
            label="Minimum margin (%)"
            type="number"
            inputMode="decimal"
            min={0}
            step={0.1}
            value={values.minimumMargin}
            placeholder="18"
            onChange={handleChange}
            error={errors.minimumMargin}
          />
        </div>

        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving..." : submitLabel}
        </Button>
      </fieldset>
    </form>
  )
}
