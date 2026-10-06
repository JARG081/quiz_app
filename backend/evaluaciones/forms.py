from django import forms

from .models import Asignacion


class AsignacionForm(forms.ModelForm):
    abre_en = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )
    cierra_en = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    class Meta:
        model = Asignacion
        fields = [
            'abre_en',
            'cierra_en',
            'intentos_permitidos',
            'tiempo_limite_minutos',
            'mostrar_respuestas',
        ]
        widgets = {
            'tiempo_limite_minutos': forms.NumberInput(attrs={'min': 1, 'max': 180}),
            'intentos_permitidos': forms.NumberInput(attrs={'min': 1, 'max': 5}),
        }

    def clean(self):
        cleaned = super().clean()
        abre_en = cleaned.get('abre_en')
        cierra_en = cleaned.get('cierra_en')
        if abre_en and cierra_en and cierra_en <= abre_en:
            self.add_error('cierra_en', 'La fecha de cierre debe ser posterior a la apertura.')
        return cleaned
