from django import forms

from courses.models import Course


class GenerateQuizForm(forms.Form):
    titulo = forms.CharField(max_length=200, label="Título del Quiz")
    course = forms.ModelChoiceField(queryset=Course.objects.none(), label="Curso")
    preguntas_solicitadas = forms.IntegerField(min_value=5, max_value=20, initial=5, label="Número de preguntas")
    tipo = forms.ChoiceField(choices=[('MC', 'Solo opción múltiple'), ('VF', 'Solo V/F'), ('MIXTO', 'Mixto')], initial='MIXTO', label="Tipo de preguntas")
    provider = forms.ChoiceField(
        choices=[
            ('AUTO', '🤖 Automático (Cambio entre proveedores si hay fallos/cuotas)'),
            ('gemini', 'Google Gemini'),
            ('deepseek', 'DeepSeek AI'),
            ('openai', 'ChatGPT (OpenAI)'),
            ('claude', 'Claude (Anthropic)'),
        ],
        initial='AUTO',
        required=False,
        label="Proveedor de IA",
    )
    instrucciones = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 3}), label="Instrucciones adicionales (opcional)")


    def __init__(self, *args, course_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = course_queryset or Course.objects.none()


class ImportQuizJsonForm(forms.Form):
    titulo = forms.CharField(max_length=200, label="Título del Quiz")
    course = forms.ModelChoiceField(queryset=Course.objects.none(), label="Curso")
    descripcion = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        label="Descripción (opcional)",
    )
    json_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 10, 'placeholder': 'Pega aquí el JSON generado por ChatGPT, Claude, Gemini, etc.'}),
        label="Pegar texto JSON",
    )
    archivo_json = forms.FileField(required=False, label="O subir archivo .json")

    def __init__(self, *args, course_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = course_queryset or Course.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        json_text = cleaned_data.get('json_text')
        archivo_json = cleaned_data.get('archivo_json')
        if not json_text and not archivo_json:
            raise forms.ValidationError("Debes pegar el JSON o subir un archivo .json.")
        return cleaned_data

